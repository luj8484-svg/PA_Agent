from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.batches import expected_intent_ref
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.contracts import unavailable_contract_rule
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ResearchStage,
    Side,
)
from pa_agent.research_backtest.domain.intents import EntryIntent, ExitIntent
from pa_agent.research_backtest.domain.market_inputs import target_event_watermark
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan, ExitExecutionPlan
from pa_agent.research_backtest.domain.rejections import (
    REASON_PRIORITY,
    portfolio_batch_subject_ref,
)
from pa_agent.research_backtest.planning.exits import build_exit_execution_plan
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from pa_agent.research_backtest.planning.funding import (
    count_funding_events,
    effective_adverse_rate_cap,
    funding_reserve,
)
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.planning.prices import adverse_gap, floor_to_step
from pa_agent.research_backtest.planning.time import next_four_hour_anchor
from pa_agent.research_backtest.testing.registry import (
    RegisteredTest,
    default_document_paths,
    load_documented_master_registry,
)
from pa_agent.research_backtest.testing.scope import scan_forbidden_capabilities
from tests.research_backtest.execution.fixtures.entry_plan_case import (
    TARGET_TIME,
    complete_entry_inputs,
)
from tests.research_backtest.execution.unit.test_batch_scaling import (
    COMMIT as BATCH_COMMIT,
)
from tests.research_backtest.execution.unit.test_batch_scaling import (
    LOCK as BATCH_LOCK,
)
from tests.research_backtest.execution.unit.test_batch_scaling import (
    TIME as BATCH_TIME,
)
from tests.research_backtest.execution.unit.test_batch_scaling import (
    complete as complete_batch,
)
from tests.research_backtest.execution.unit.test_contract_cost_funding import (
    HOUR,
    prior_approx,
    risk_config,
    schedule,
)
from tests.research_backtest.execution.unit.test_entry_intent_time_market import candidate
from tests.research_backtest.execution.unit.test_price_gap_sizing import (
    contract as sizing_contract,
)
from tests.research_backtest.execution.unit.test_price_gap_sizing import inputs as sizing_inputs
from tests.research_backtest.execution.unit.test_scheduled_exit_planning import (
    condition as exit_condition,
)
from tests.research_backtest.execution.unit.test_scheduled_exit_planning import (
    planning_inputs,
)

ROOT = Path(__file__).resolve().parents[4]
THIS_FILE = Path(__file__).resolve()
SCENARIO_PATH = (
    ROOT / "tests" / "research_backtest" / "execution" / "fixtures" / "frozen_case_scenarios_v1.tsv"
)
LOCKED_MASTER_REGISTRY_HASH = "e56d6e6de968671b6e546d593f0f7624a4233b3772bf49f8bae38879d9ee2ca9"
LOCKED_EXPLICIT_TEST_SET_HASH = "d9955f044a13f365598a39586220f14208d3842ea950de6beb07b7a10eaad3bc"
EXPLICIT_ID_PATTERN = re.compile(r'(?:registered|test_id)\("([A-Z0-9-]+)"')


def _documented() -> tuple[RegisteredTest, ...]:
    values = load_documented_master_registry(default_document_paths(ROOT))
    digest = canonical_sha256(tuple((item.test_id, item.requirement_ids) for item in values))
    if digest != LOCKED_MASTER_REGISTRY_HASH:
        raise RuntimeError("frozen MASTER_TEST_REGISTRY_V1 content changed")
    return values


def _explicit_test_ids() -> frozenset[str]:
    values: set[str] = set()
    execution_root = ROOT / "tests" / "research_backtest" / "execution"
    for path in execution_root.rglob("*.py"):
        if path.resolve() == THIS_FILE:
            continue
        values.update(EXPLICIT_ID_PATTERN.findall(path.read_text(encoding="utf-8")))
    digest = canonical_sha256(tuple(sorted(values)))
    if digest != LOCKED_EXPLICIT_TEST_SET_HASH:
        raise RuntimeError("explicit 2B test set changed without scenario re-freeze")
    return frozenset(values)


DOCUMENTED = _documented()
EXPLICIT_TEST_IDS = _explicit_test_ids()
MATRIX_CASES = tuple(item for item in DOCUMENTED if item.test_id not in EXPLICIT_TEST_IDS)


def _corrupt_frozen(value, **changes):
    forged = object.__new__(type(value))
    for field in fields(type(value)):
        object.__setattr__(forged, field.name, changes.get(field.name, getattr(value, field.name)))
    return forged


def canonical_round_trip(record) -> str:
    value = Decimal(record["inputs"]["decimal"])
    left = canonical_dumps({"b": value, "a": (record["test_id"], record["inputs"]["seed"])})
    right = canonical_dumps({"a": (record["test_id"], record["inputs"]["seed"]), "b": value})
    assert left == right
    assert canonical_sha256(left) == canonical_sha256(right)
    return canonical_sha256(left)


def time_anchor(record) -> str:
    anchor = (record["inputs"]["seed"] % 1000 + 1) * 14_400_000
    assert next_four_hour_anchor(anchor - 1) == anchor
    return str(anchor)


def delay_domain(record) -> str:
    delay = record["inputs"]["delay"]
    assert execution_time_config(entry_delay_minutes=delay, exit_delay_minutes=delay)
    for invalid in (-1, 3, True, False):
        with pytest.raises(ValueError):
            execution_time_config(entry_delay_minutes=invalid, exit_delay_minutes=1)
    return str(delay)


def delay_identity(record) -> str:
    source = candidate()
    values = tuple(
        make_entry_intent(
            source,
            execution_time_config(entry_delay_minutes=delay, exit_delay_minutes=1),
            computational_experiment_id="f" * 64,
            stage=ResearchStage.BACKTEST,
            code_commit="c" * 40,
            dependency_lock_hash="e" * 64,
        )
        for delay in (0, 1, 2)
    )
    assert len({item.intent_id for item in values}) == 3
    assert {item.candidate_id for item in values} == {source.candidate_id}
    return canonical_sha256(tuple(item.intent_id for item in values))


def cost_slippage(record) -> str:
    multiplier = Decimal("1") + Decimal(record["inputs"]["delay"]) / Decimal("2")
    cost = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=multiplier,
    )
    assert cost.effective_fee_rate == Decimal("0.0005") * multiplier
    assert cost.effective_slippage_rate == Decimal("0.0001") * multiplier
    return f"{cost.effective_fee_rate}|{cost.effective_slippage_rate}"


def funding_reserve_case(record) -> str:
    quantity = Decimal(record["inputs"]["decimal"])
    expected = quantity * Decimal("125") * Decimal("0.0002") * 3
    actual = funding_reserve(quantity, Decimal("125"), Decimal("0.0002"), 3)
    assert actual == expected
    return str(actual)


def funding_schedule_semantics(record) -> str:
    requirement = next(item for item in record["requirement_ids"] if item.startswith("2B-FUND-"))
    if requirement == "2B-FUND-001":
        value = schedule(windows=((8 * HOUR, 8 * HOUR, 8 * HOUR),))
        return f"{count_funding_events(8 * HOUR, 9 * HOUR, value)}|{count_funding_events(8 * HOUR - 1, 8 * HOUR, value)}"
    if requirement == "2B-FUND-002":
        value = schedule(windows=((8 * HOUR - 1_000, 8 * HOUR, 8 * HOUR + 1_000),))
        return f"{count_funding_events(8 * HOUR + 999, 9 * HOUR, value)}|{count_funding_events(8 * HOUR + 1_000, 9 * HOUR, value)}"
    if requirement == "2B-FUND-003":
        value = schedule(windows=((12 * HOUR, 12 * HOUR, 12 * HOUR + 1_000),))
        return str(count_funding_events(10 * HOUR, 12 * HOUR, value))
    if requirement == "2B-FUND-004":
        windows = tuple((hour * HOUR, hour * HOUR, hour * HOUR) for hour in (6, 12, 24, 27))
        return str(count_funding_events(0, 30 * HOUR, schedule(windows=windows)))
    if requirement == "2B-FUND-005":
        value = schedule(effective_from=1, effective_to=20 * HOUR)
        failures = 0
        for entry, exit_time in ((0, 10 * HOUR), (10 * HOUR, 20 * HOUR)):
            with pytest.raises(ValueError, match="does not cover"):
                count_funding_events(entry, exit_time, value)
            failures += 1
        return f"COVERAGE_REJECTED|{failures}"
    if requirement == "2B-FUND-006":
        entry = 1_000_000
        windows = tuple(
            (
                entry + index * 8 * HOUR - 1_000,
                entry + index * 8 * HOUR,
                entry + index * 8 * HOUR + 1_000,
            )
            for index in range(7)
        )
        value = schedule(
            windows=windows,
            effective_from=entry - 1_000,
            effective_to=entry + 48 * HOUR + 1_001,
        )
        return str(count_funding_events(entry, entry + 48 * HOUR, value))
    raise AssertionError(f"unsupported funding schedule requirement: {requirement}")


def funding_config_semantics(record) -> str:
    requirement = next(item for item in record["requirement_ids"] if item.startswith("2B-FUND-"))
    if requirement == "2B-FUND-007":
        from pa_agent.research_backtest.domain.funding import covered_funding_risk_config

        with pytest.raises(ValueError, match="target coverage"):
            covered_funding_risk_config(
                symbol="BTCUSDT",
                target_time_utc_ms=10 * HOUR,
                adverse_rate_cap=Decimal("0.0001"),
                effective_from_utc_ms=0,
                effective_to_utc_ms=10 * HOUR,
                source_kind="REVIEWED_ARCHIVE",
                source_manifest_hash="a" * 64,
                verification_mode="VERIFIED",
                stress_multiplier=Decimal("1"),
                watermark="VERIFIED",
                evidence_time_utc_ms=10 * HOUR,
                code_commit="c" * 40,
                dependency_lock_hash="b" * 64,
            )
        return "TARGET_COVERAGE_REJECTED"
    if requirement == "2B-FUND-008":
        value = risk_config()
        with pytest.raises(ValueError, match="watermark"):
            replace(value, watermark="VERIFIED")
        return f"{value.adverse_rate_cap}|{value.watermark}"
    if requirement == "2B-FUND-009":
        rates = tuple(
            effective_adverse_rate_cap(risk_config(stress=value))
            for value in (Decimal("1"), Decimal("1.5"), Decimal("2"))
        )
        assert rates == tuple(sorted(rates))
        return "|".join(str(item) for item in rates)
    raise AssertionError(f"unsupported funding config requirement: {requirement}")


def risk_sizing_formula(record) -> str:
    requirement = next(item for item in record["requirement_ids"] if item.startswith("2B-RISK-"))
    sizing = __import__(
        "pa_agent.research_backtest.planning.sizing", fromlist=["position_sizing"]
    ).position_sizing(sizing_inputs())
    if requirement == "2B-RISK-001":
        return str(sizing.unit_risk)
    if requirement == "2B-RISK-002":
        assert sizing.single_risk_budget == Decimal("50.000")
        return str(sizing.single_risk_budget)
    if requirement == "2B-RISK-003":
        assert sizing.raw_quantity == sizing.single_risk_budget / sizing.unit_risk
        return str(sizing.raw_quantity)
    if requirement == "2B-RISK-004":
        planned = sizing.step_quantized_quantity * sizing.unit_risk
        assert planned <= sizing.single_risk_budget
        return f"{planned}|{sizing.single_risk_budget}"
    if requirement == "2B-RISK-009":
        with pytest.raises(ValueError):
            replace(sizing, step_quantized_quantity=sizing.raw_quantity + Decimal("1"))
        return "RISK_INVARIANT_REJECTED"
    if requirement == "2B-RISK-010":
        result = __import__(
            "pa_agent.research_backtest.planning.sizing", fromlist=["position_sizing"]
        ).position_sizing(replace(sizing_inputs(), open_risk_evidence_records=None))
        return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"
    raise AssertionError(f"unsupported sizing requirement: {requirement}")


def portfolio_risk_semantics(record) -> str:
    from pa_agent.research_backtest.planning.portfolio import scale_portfolio

    result = scale_portfolio(*complete_batch(balance=Decimal("1000")))
    accepted_risk = sum(
        (getattr(item, "final_planned_risk", Decimal("0")) for item in result.item_results),
        Decimal("0"),
    )
    assert result.final_scale <= 1
    return f"{result.final_scale}|{accepted_risk}"


def quantity_floor(record) -> str:
    integer = Decimal(record["inputs"]["seed"] % 100 + 1)
    raw = integer + Decimal("0.009")
    actual = floor_to_step(raw, Decimal("0.01"))
    assert actual == integer
    return str(actual)


def gap_boundary(record) -> str:
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("105"), Decimal("10")) == 5
    assert adverse_gap(Side.SHORT, Decimal("100"), Decimal("95"), Decimal("10")) == 5
    with pytest.raises(ValueError, match="GAP_TOO_LARGE"):
        adverse_gap(Side.LONG, Decimal("100"), Decimal("105.1"), Decimal("10"))
    return ExecutionRejectionReason.GAP_TOO_LARGE.value


def schema_lifecycle(record) -> str:
    assert all(
        is_dataclass(value)
        for value in (EntryIntent, ExitIntent, EntryExecutionPlan, ExitExecutionPlan)
    )
    entry_names = {field.name for field in fields(EntryExecutionPlan)}
    exit_names = {field.name for field in fields(ExitExecutionPlan)}
    assert "unit_risk" in entry_names - exit_names
    assert "scheduled_exit_reason" in exit_names - entry_names
    assert "item_input_hash" not in canonical_dumps(complete_batch()[0])
    plan = build_entry_execution_plan(complete_entry_inputs())
    with pytest.raises(ValueError, match="exact integer 1"):
        replace(plan, leverage=True)
    return f"{len(entry_names)}|{len(exit_names)}"


def rejection_priority(record) -> str:
    assert set(REASON_PRIORITY) == set(ExecutionRejectionReason)
    assert len(set(REASON_PRIORITY.values())) == len(REASON_PRIORITY)
    assert REASON_PRIORITY[ExecutionRejectionReason.DATA_INVALID] == min(REASON_PRIORITY.values())
    return ExecutionRejectionReason.DATA_INVALID.value


def scope_guard(record) -> str:
    package_root = ROOT / "pa_agent" / "research_backtest"
    paths = tuple(
        sorted(
            (*((package_root / "domain").glob("*.py")), *((package_root / "planning").glob("*.py")))
        )
    )
    actual = scan_forbidden_capabilities(paths, package_root=package_root)
    assert actual == ()
    return str(len(actual))


def golden_entry(record) -> str:
    actual = build_entry_execution_plan(complete_entry_inputs())
    expected = json.loads(
        (SCENARIO_PATH.parent / "execution_golden_v1.json").read_text(encoding="utf-8")
    )
    assert actual.plan_id == expected["entry_plan_id"]
    assert (
        hashlib.sha256(actual.canonical_json().encode()).hexdigest()
        == expected["entry_plan_canonical_sha256"]
    )
    return actual.plan_id


def golden_exit(record) -> str:
    actual = build_exit_execution_plan(planning_inputs())
    expected = json.loads(
        (SCENARIO_PATH.parent / "execution_golden_v1.json").read_text(encoding="utf-8")
    )
    assert actual.plan_id == expected["exit_plan_id"]
    assert (
        hashlib.sha256(actual.canonical_json().encode()).hexdigest()
        == expected["exit_plan_canonical_sha256"]
    )
    return actual.plan_id


def missing_target(record) -> str:
    result = build_entry_execution_plan(replace(complete_entry_inputs(), target_open=None))
    assert result.reason is ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def missing_account(record) -> str:
    inputs = complete_entry_inputs()
    field = "account" if record["inputs"]["seed"] % 2 else "account_evidence_records"
    result = build_entry_execution_plan(replace(inputs, **{field: None}))
    assert result.reason is ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def missing_contract(record) -> str:
    inputs = complete_entry_inputs()
    unavailable = unavailable_contract_rule(
        symbol=inputs.intent.symbol,
        query_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    result = build_entry_execution_plan(replace(inputs, contract=unavailable))
    assert result.reason is ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def account_replay(record) -> str:
    inputs = complete_entry_inputs()
    field = "current_equity" if record["inputs"]["seed"] % 2 else "existing_open_risk"
    forged = _corrupt_frozen(inputs.account, **{field: getattr(inputs.account, field) + 1})
    result = build_entry_execution_plan(replace(inputs, account=forged))
    assert result.reason is ExecutionRejectionReason.DATA_INVALID
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def contract_modes(record) -> str:
    return missing_contract(record)


def contract_expiry(record) -> str:
    inputs = complete_entry_inputs()
    expired = _corrupt_frozen(inputs.contract, effective_to_utc_ms=TARGET_TIME)
    result = build_entry_execution_plan(replace(inputs, contract=expired))
    assert result.reason is ExecutionRejectionReason.CONTRACT_RULE_EXPIRED
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def stage_contract_gate(record) -> str:
    inputs = complete_entry_inputs()
    unavailable = unavailable_contract_rule(
        symbol=inputs.intent.symbol,
        query_time_utc_ms=TARGET_TIME,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    results = tuple(
        build_entry_execution_plan(replace(inputs, contract=unavailable, stage=stage))
        for stage in ResearchStage
    )
    assert {dict(item.required_values)["research_stage"] for item in results} == {
        stage.value for stage in ResearchStage
    }
    assert all(
        item.reason is ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE for item in results
    )
    return "|".join(item.disposition.value for item in results)


def minimum_rejection(record) -> str:
    result = __import__(
        "pa_agent.research_backtest.planning.sizing", fromlist=["position_sizing"]
    ).position_sizing(sizing_inputs(rule=sizing_contract(min_qty=Decimal("999"))))
    assert result.reason is ExecutionRejectionReason.BELOW_MIN_QTY
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def portfolio_scaling(record) -> str:
    from pa_agent.research_backtest.planning.portfolio import scale_portfolio

    args = complete_batch(balance=Decimal("1000"))
    first = scale_portfolio(*args)
    second = scale_portfolio(*args)
    assert first == second
    assert first.portfolio_planning_batch_id == args[0].batch_id
    return str(first.final_scale)


def batch_completeness(record) -> str:
    batch, _, _, _, opens, _ = complete_batch()
    assert batch.target_open_snapshot_ids == tuple(item.snapshot_id for item in opens)
    assert batch.ordered_successful_sizing_result_ids
    return str(len(batch.ordered_resolution_refs))


def incomplete_batch_lifecycle(record) -> str:
    from pa_agent.research_backtest.planning.portfolio import resolve_batch_completeness

    batch, account, _, _, opens, stage = complete_batch()
    expected = tuple(
        expected_intent_ref(intent_id, symbol, batch.eligible_time_utc_ms)
        for intent_id, symbol in zip(
            batch.ordered_entry_intent_ids, batch.ordered_symbols, strict=True
        )
    )
    subject = portfolio_batch_subject_ref(
        portfolio_planning_batch_id=batch.batch_id,
        symbols=batch.ordered_symbols,
        ordered_entry_intent_ids=batch.ordered_entry_intent_ids,
        batch_content_hash=batch.batch_content_hash,
        account_snapshot_hash=account.snapshot_hash,
        target_open_snapshot_hashes=tuple(item.snapshot_content_hash for item in opens),
    )
    result = resolve_batch_completeness(
        expected,
        (),
        subject=subject,
        completeness_event_time_utc_ms=BATCH_TIME,
        source_event_id="generated-incomplete-event",
        stage=stage,
        code_commit=BATCH_COMMIT,
        dependency_lock_hash=BATCH_LOCK,
    )
    assert result.reason is ExecutionRejectionReason.BATCH_INCOMPLETE
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def exit_anchor(record) -> str:
    intent = planning_inputs().intent
    assert intent.execution_anchor_utc_ms <= intent.target_execution_time_utc_ms
    assert intent.target_execution_time_utc_ms - intent.execution_anchor_utc_ms == 60_000
    return f"{intent.execution_anchor_utc_ms}|{intent.target_execution_time_utc_ms}"


def exit_condition_anchor(record) -> str:
    condition = exit_condition()
    intent = planning_inputs().intent
    expected_anchor = (condition.condition_time_utc_ms // 60_000) * 60_000 + 60_000
    assert intent.execution_anchor_utc_ms == expected_anchor
    return f"{condition.condition_time_utc_ms}|{expected_anchor}"


def split_identity_and_boundary(record) -> str:
    inputs = complete_entry_inputs()
    baseline = build_entry_execution_plan(inputs)
    wider = build_entry_execution_plan(
        replace(
            inputs,
            split_start_utc_ms=max(0, inputs.split_start_utc_ms - 1),
            split_end_utc_ms=inputs.split_end_utc_ms + 1,
        )
    )
    assert wider.plan_id == baseline.plan_id
    invalid = build_entry_execution_plan(
        replace(inputs, split_end_utc_ms=inputs.intent.target_execution_time_utc_ms)
    )
    assert invalid.reason is ExecutionRejectionReason.DATA_INVALID
    return f"{baseline.plan_id}|{invalid.reason.value}"


def approximated_evidence_time(record) -> str:
    exact = prior_approx(evidence_time=10 * HOUR)
    assert exact.evidence_time_utc_ms == exact.query_time_utc_ms
    with pytest.raises(ValueError, match="future evidence"):
        prior_approx(evidence_time=10 * HOUR + 1)
    return f"{exact.mode.value}|{exact.approximation_direction.value}"


def completeness_time_guard(record) -> str:
    from pa_agent.research_backtest.domain.batches import (
        portfolio_batch_completeness_snapshot,
        resolution_ref,
    )
    from pa_agent.research_backtest.domain.enums import ResolutionKind

    expected = (expected_intent_ref("eint_" + "1" * 24, "BTCUSDT", BATCH_TIME),)
    resolution = resolution_ref(
        expected[0].entry_intent_id,
        "BTCUSDT",
        ResolutionKind.EXECUTION_PATH_INVALID,
        "rej_" + "1" * 24,
        "a" * 64,
    )
    with pytest.raises(ValueError, match="event time"):
        portfolio_batch_completeness_snapshot(
            expected,
            (resolution,),
            completeness_event_time_utc_ms=BATCH_TIME - 1,
            source_event_id="generated-too-early-completeness",
            code_commit=BATCH_COMMIT,
            dependency_lock_hash=BATCH_LOCK,
        )
    return "COMPLETENESS_EVENT_REJECTED"


def valuation_time_guard(record) -> str:
    from pa_agent.research_backtest.domain.accounts import make_account_planning_snapshot
    from tests.research_backtest.execution.unit.test_account_evidence import (
        ELIGIBLE,
        bundle,
    )

    evidence_bundle, evidence = bundle()
    with pytest.raises(ValueError, match="eligible time"):
        make_account_planning_snapshot(evidence_bundle, evidence, eligible_time_utc_ms=ELIGIBLE + 1)
    return "VALUATION_TIME_REJECTED"


def watermark_identity(record) -> str:
    inputs = complete_entry_inputs()
    baseline = build_entry_execution_plan(inputs)
    later = target_event_watermark(
        symbol=inputs.watermark.symbol,
        target_open_time_utc_ms=inputs.watermark.target_open_time_utc_ms,
        event_watermark_time_utc_ms=inputs.watermark.event_watermark_time_utc_ms + 60_000,
        watermark_source_event_id="later-watermark-event",
        watermark_source_stream_version=inputs.watermark.watermark_source_stream_version,
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )
    # Snapshot and Plan identity are independent of the consumption watermark object.
    replay = build_entry_execution_plan(replace(inputs, watermark=later))
    assert replay.plan_id == baseline.plan_id
    return baseline.plan_id


def plan_chain(record) -> str:
    inputs = complete_entry_inputs()
    plan = build_entry_execution_plan(inputs)
    assert plan.portfolio_planning_batch_id == inputs.batch.batch_id
    assert plan.portfolio_scaling_result_id == inputs.scaling.result_id
    assert plan.accepted_scaling_item_id == inputs.accepted_item.item_id
    return plan.plan_id


def exact_48h(record) -> str:
    plan = build_entry_execution_plan(complete_entry_inputs())
    assert plan.maximum_exit_time_utc_ms - plan.target_execution_time_utc_ms == 172_800_000
    return str(plan.maximum_exit_time_utc_ms - plan.target_execution_time_utc_ms)


def identity_self_validation(record) -> str:
    plan = build_entry_execution_plan(complete_entry_inputs())
    with pytest.raises(ValueError, match="Canonical content"):
        replace(plan, plan_id="eplan_" + "0" * 24)
    return "IDENTITY_MISMATCH_REJECTED"


def target_precondition(record) -> str:
    inputs = complete_entry_inputs()
    watermark = target_event_watermark(
        symbol=inputs.watermark.symbol,
        target_open_time_utc_ms=TARGET_TIME,
        event_watermark_time_utc_ms=TARGET_TIME - 1,
        watermark_source_event_id="early-watermark-event",
        watermark_source_stream_version=inputs.watermark.watermark_source_stream_version,
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )
    with pytest.raises(ValueError, match="not reached"):
        build_entry_execution_plan(replace(inputs, target_open=None, watermark=watermark))
    return "TARGET_NOT_REACHED"


def exit_quantity_mismatch(record) -> str:
    inputs = planning_inputs()
    result = build_exit_execution_plan(replace(inputs, target_position_snapshot_hash="8" * 64))
    assert result.reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED
    return f"{result.reason.value}|{result.disposition.value}|{result.retry_allowed}"


def registry_bijection(record) -> str:
    assert len(DOCUMENTED) == 435
    assert {item.test_id for item in DOCUMENTED} == EXPLICIT_TEST_IDS | {
        item.test_id for item in MATRIX_CASES
    }
    return str(len(DOCUMENTED))


ADAPTERS: dict[str, Callable[[dict[str, object]], str]] = {
    "account_replay": account_replay,
    "approximated_evidence_time": approximated_evidence_time,
    "batch_completeness": batch_completeness,
    "canonical_round_trip": canonical_round_trip,
    "contract_expiry": contract_expiry,
    "contract_modes": contract_modes,
    "completeness_time_guard": completeness_time_guard,
    "cost_slippage": cost_slippage,
    "delay_domain": delay_domain,
    "delay_identity": delay_identity,
    "exact_48h": exact_48h,
    "exit_anchor": exit_anchor,
    "exit_condition_anchor": exit_condition_anchor,
    "exit_quantity_mismatch": exit_quantity_mismatch,
    "funding_config_semantics": funding_config_semantics,
    "funding_reserve": funding_reserve_case,
    "funding_schedule_semantics": funding_schedule_semantics,
    "gap_boundary": gap_boundary,
    "golden_entry": golden_entry,
    "golden_exit": golden_exit,
    "identity_self_validation": identity_self_validation,
    "incomplete_batch_lifecycle": incomplete_batch_lifecycle,
    "minimum_rejection": minimum_rejection,
    "missing_account": missing_account,
    "missing_contract": missing_contract,
    "missing_target": missing_target,
    "plan_chain": plan_chain,
    "portfolio_scaling": portfolio_scaling,
    "portfolio_risk_semantics": portfolio_risk_semantics,
    "quantity_floor": quantity_floor,
    "registry_bijection": registry_bijection,
    "rejection_priority": rejection_priority,
    "risk_sizing_formula": risk_sizing_formula,
    "schema_lifecycle": schema_lifecycle,
    "scope_guard": scope_guard,
    "split_identity_and_boundary": split_identity_and_boundary,
    "stage_contract_gate": stage_contract_gate,
    "target_precondition": target_precondition,
    "time_anchor": time_anchor,
    "valuation_time_guard": valuation_time_guard,
    "watermark_identity": watermark_identity,
}


def _load_scenarios() -> dict[str, dict[str, object]]:
    lines = SCENARIO_PATH.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != (
        "test_id\tadapter\trequirement_ids\tseed\tdecimal\tdelay\texpected_value"
    ):
        raise RuntimeError("unsupported frozen scenario schema")
    result: dict[str, dict[str, object]] = {}
    for line in lines[1:]:
        test_id, adapter, requirement_ids, seed, decimal_value, delay, expected_value = line.split(
            "\t"
        )
        if test_id in result:
            raise RuntimeError(f"duplicate frozen scenario: {test_id}")
        requirements = requirement_ids.split(",")
        result[test_id] = {
            "test_id": test_id,
            "adapter": adapter,
            "requirement_ids": requirements,
            "inputs": {"seed": int(seed), "decimal": decimal_value, "delay": int(delay)},
            "expected_value": expected_value,
        }
    return result


SCENARIOS = _load_scenarios()
EXPECTED_MATRIX_IDS = {item.test_id for item in MATRIX_CASES}
if set(SCENARIOS) != EXPECTED_MATRIX_IDS:
    raise RuntimeError("every generated test ID requires exactly one frozen scenario record")
if any(item["adapter"] not in ADAPTERS for item in SCENARIOS.values()):
    raise RuntimeError("frozen scenario references an unimplemented adapter")


def _param(item: RegisteredTest):
    return pytest.param(
        item,
        id=item.test_id,
        marks=(
            pytest.mark.test_id(item.test_id),
            pytest.mark.requirement_ids(*item.requirement_ids),
        ),
    )


@pytest.mark.parametrize("case", tuple(_param(item) for item in MATRIX_CASES))
def test_frozen_matrix_case(case: RegisteredTest) -> None:
    record = SCENARIOS[case.test_id]
    assert tuple(record["requirement_ids"]) == case.requirement_ids
    actual = ADAPTERS[record["adapter"]](record)
    assert actual == record["expected_value"]
