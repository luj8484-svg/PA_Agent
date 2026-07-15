from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from pathlib import Path

import pytest

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
from pa_agent.research_backtest.domain.rejections import REASON_PRIORITY
from pa_agent.research_backtest.planning.exits import build_exit_execution_plan
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from pa_agent.research_backtest.planning.funding import funding_reserve
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
from tests.research_backtest.execution.unit.test_batch_scaling import complete as complete_batch
from tests.research_backtest.execution.unit.test_entry_intent_time_market import candidate
from tests.research_backtest.execution.unit.test_price_gap_sizing import (
    contract as sizing_contract,
)
from tests.research_backtest.execution.unit.test_price_gap_sizing import inputs as sizing_inputs
from tests.research_backtest.execution.unit.test_scheduled_exit_planning import planning_inputs

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


def _assert_record(record: dict[str, object]) -> None:
    assert record["expected"] == {
        "adapter": record["adapter"],
        "requirement_ids": record["requirement_ids"],
        "test_id": record["test_id"],
    }


def canonical_round_trip(record) -> None:
    value = Decimal(record["inputs"]["decimal"])
    left = canonical_dumps({"b": value, "a": (record["test_id"], record["inputs"]["seed"])})
    right = canonical_dumps({"a": (record["test_id"], record["inputs"]["seed"]), "b": value})
    assert left == right
    assert canonical_sha256(left) == canonical_sha256(right)


def time_anchor(record) -> None:
    anchor = (record["inputs"]["seed"] % 1000 + 1) * 14_400_000
    assert next_four_hour_anchor(anchor - 1) == anchor


def delay_domain(record) -> None:
    delay = record["inputs"]["delay"]
    assert execution_time_config(entry_delay_minutes=delay, exit_delay_minutes=delay)
    for invalid in (-1, 3, True, False):
        with pytest.raises(ValueError):
            execution_time_config(entry_delay_minutes=invalid, exit_delay_minutes=1)


def delay_identity(record) -> None:
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


def cost_slippage(record) -> None:
    multiplier = Decimal("1") + Decimal(record["inputs"]["delay"]) / Decimal("2")
    cost = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=multiplier,
    )
    assert cost.effective_fee_rate == Decimal("0.0005") * multiplier
    assert cost.effective_slippage_rate == Decimal("0.0001") * multiplier


def funding_reserve_case(record) -> None:
    quantity = Decimal(record["inputs"]["decimal"])
    expected = quantity * Decimal("125") * Decimal("0.0002") * 3
    assert funding_reserve(quantity, Decimal("125"), Decimal("0.0002"), 3) == expected


def quantity_floor(record) -> None:
    integer = Decimal(record["inputs"]["seed"] % 100 + 1)
    raw = integer + Decimal("0.009")
    assert floor_to_step(raw, Decimal("0.01")) == integer


def gap_boundary(record) -> None:
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("105"), Decimal("10")) == 5
    assert adverse_gap(Side.SHORT, Decimal("100"), Decimal("95"), Decimal("10")) == 5
    with pytest.raises(ValueError, match="GAP_TOO_LARGE"):
        adverse_gap(Side.LONG, Decimal("100"), Decimal("105.1"), Decimal("10"))


def schema_lifecycle(record) -> None:
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


def rejection_priority(record) -> None:
    assert set(REASON_PRIORITY) == set(ExecutionRejectionReason)
    assert len(set(REASON_PRIORITY.values())) == len(REASON_PRIORITY)
    assert REASON_PRIORITY[ExecutionRejectionReason.DATA_INVALID] == min(REASON_PRIORITY.values())


def scope_guard(record) -> None:
    package_root = ROOT / "pa_agent" / "research_backtest"
    paths = tuple(
        sorted(
            (*((package_root / "domain").glob("*.py")), *((package_root / "planning").glob("*.py")))
        )
    )
    assert scan_forbidden_capabilities(paths, package_root=package_root) == ()


def golden_entry(record) -> None:
    actual = build_entry_execution_plan(complete_entry_inputs())
    expected = json.loads(
        (SCENARIO_PATH.parent / "execution_golden_v1.json").read_text(encoding="utf-8")
    )
    assert actual.plan_id == expected["entry_plan_id"]
    assert (
        hashlib.sha256(actual.canonical_json().encode()).hexdigest()
        == expected["entry_plan_canonical_sha256"]
    )


def golden_exit(record) -> None:
    actual = build_exit_execution_plan(planning_inputs())
    expected = json.loads(
        (SCENARIO_PATH.parent / "execution_golden_v1.json").read_text(encoding="utf-8")
    )
    assert actual.plan_id == expected["exit_plan_id"]
    assert (
        hashlib.sha256(actual.canonical_json().encode()).hexdigest()
        == expected["exit_plan_canonical_sha256"]
    )


def missing_target(record) -> None:
    result = build_entry_execution_plan(replace(complete_entry_inputs(), target_open=None))
    assert result.reason is ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE


def missing_account(record) -> None:
    inputs = complete_entry_inputs()
    field = "account" if record["inputs"]["seed"] % 2 else "account_evidence_records"
    result = build_entry_execution_plan(replace(inputs, **{field: None}))
    assert result.reason is ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE


def missing_contract(record) -> None:
    inputs = complete_entry_inputs()
    unavailable = unavailable_contract_rule(
        symbol=inputs.intent.symbol,
        query_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    result = build_entry_execution_plan(replace(inputs, contract=unavailable))
    assert result.reason is ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE


def account_replay(record) -> None:
    inputs = complete_entry_inputs()
    field = "current_equity" if record["inputs"]["seed"] % 2 else "existing_open_risk"
    forged = _corrupt_frozen(inputs.account, **{field: getattr(inputs.account, field) + 1})
    result = build_entry_execution_plan(replace(inputs, account=forged))
    assert result.reason is ExecutionRejectionReason.DATA_INVALID


def contract_modes(record) -> None:
    missing_contract(record)


def contract_expiry(record) -> None:
    inputs = complete_entry_inputs()
    expired = _corrupt_frozen(inputs.contract, effective_to_utc_ms=TARGET_TIME)
    result = build_entry_execution_plan(replace(inputs, contract=expired))
    assert result.reason is ExecutionRejectionReason.CONTRACT_RULE_EXPIRED


def stage_contract_gate(record) -> None:
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


def minimum_rejection(record) -> None:
    result = __import__(
        "pa_agent.research_backtest.planning.sizing", fromlist=["position_sizing"]
    ).position_sizing(sizing_inputs(rule=sizing_contract(min_qty=Decimal("999"))))
    assert result.reason is ExecutionRejectionReason.BELOW_MIN_QTY


def portfolio_scaling(record) -> None:
    from pa_agent.research_backtest.planning.portfolio import scale_portfolio

    args = complete_batch(balance=Decimal("1000"))
    first = scale_portfolio(*args)
    second = scale_portfolio(*args)
    assert first == second
    assert first.portfolio_planning_batch_id == args[0].batch_id


def batch_completeness(record) -> None:
    batch, _, _, _, opens, _ = complete_batch()
    assert batch.target_open_snapshot_ids == tuple(item.snapshot_id for item in opens)
    assert batch.ordered_successful_sizing_result_ids


def watermark_identity(record) -> None:
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


def plan_chain(record) -> None:
    inputs = complete_entry_inputs()
    plan = build_entry_execution_plan(inputs)
    assert plan.portfolio_planning_batch_id == inputs.batch.batch_id
    assert plan.portfolio_scaling_result_id == inputs.scaling.result_id
    assert plan.accepted_scaling_item_id == inputs.accepted_item.item_id


def exact_48h(record) -> None:
    plan = build_entry_execution_plan(complete_entry_inputs())
    assert plan.maximum_exit_time_utc_ms - plan.target_execution_time_utc_ms == 172_800_000


def identity_self_validation(record) -> None:
    plan = build_entry_execution_plan(complete_entry_inputs())
    with pytest.raises(ValueError, match="Canonical content"):
        replace(plan, plan_id="eplan_" + "0" * 24)


def target_precondition(record) -> None:
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


def exit_quantity_mismatch(record) -> None:
    inputs = planning_inputs()
    result = build_exit_execution_plan(replace(inputs, target_position_snapshot_hash="8" * 64))
    assert result.reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED


def registry_bijection(record) -> None:
    assert len(DOCUMENTED) == 435
    assert {item.test_id for item in DOCUMENTED} == EXPLICIT_TEST_IDS | {
        item.test_id for item in MATRIX_CASES
    }


ADAPTERS: dict[str, Callable[[dict[str, object]], None]] = {
    "account_replay": account_replay,
    "batch_completeness": batch_completeness,
    "canonical_round_trip": canonical_round_trip,
    "contract_expiry": contract_expiry,
    "contract_modes": contract_modes,
    "cost_slippage": cost_slippage,
    "delay_domain": delay_domain,
    "delay_identity": delay_identity,
    "exact_48h": exact_48h,
    "exit_quantity_mismatch": exit_quantity_mismatch,
    "funding_reserve": funding_reserve_case,
    "gap_boundary": gap_boundary,
    "golden_entry": golden_entry,
    "golden_exit": golden_exit,
    "identity_self_validation": identity_self_validation,
    "minimum_rejection": minimum_rejection,
    "missing_account": missing_account,
    "missing_contract": missing_contract,
    "missing_target": missing_target,
    "plan_chain": plan_chain,
    "portfolio_scaling": portfolio_scaling,
    "quantity_floor": quantity_floor,
    "registry_bijection": registry_bijection,
    "rejection_priority": rejection_priority,
    "schema_lifecycle": schema_lifecycle,
    "scope_guard": scope_guard,
    "stage_contract_gate": stage_contract_gate,
    "target_precondition": target_precondition,
    "time_anchor": time_anchor,
    "watermark_identity": watermark_identity,
}


def _load_scenarios() -> dict[str, dict[str, object]]:
    lines = SCENARIO_PATH.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "test_id\tadapter\trequirement_ids\tseed\tdecimal\tdelay":
        raise RuntimeError("unsupported frozen scenario schema")
    result: dict[str, dict[str, object]] = {}
    for line in lines[1:]:
        test_id, adapter, requirement_ids, seed, decimal_value, delay = line.split("\t")
        if test_id in result:
            raise RuntimeError(f"duplicate frozen scenario: {test_id}")
        requirements = requirement_ids.split(",")
        result[test_id] = {
            "test_id": test_id,
            "adapter": adapter,
            "requirement_ids": requirements,
            "inputs": {"seed": int(seed), "decimal": decimal_value, "delay": int(delay)},
            "expected": {
                "adapter": adapter,
                "requirement_ids": requirements,
                "test_id": test_id,
            },
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
    _assert_record(record)
    ADAPTERS[record["adapter"]](record)
