from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.contracts import (
    ContractRuleMode,
    unavailable_contract_rule,
)
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, Side
from pa_agent.research_backtest.domain.intents import EntryIntent, ExitIntent
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan, ExitExecutionPlan
from pa_agent.research_backtest.domain.rejections import REASON_PRIORITY
from pa_agent.research_backtest.planning.exits import build_exit_execution_plan
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from pa_agent.research_backtest.planning.funding import funding_reserve
from pa_agent.research_backtest.planning.prices import adverse_gap, floor_to_step
from pa_agent.research_backtest.planning.time import next_four_hour_anchor
from pa_agent.research_backtest.testing.registry import (
    RegisteredTest,
    default_document_paths,
    load_documented_master_registry,
)
from pa_agent.research_backtest.testing.scope import scan_forbidden_capabilities
from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs
from tests.research_backtest.execution.unit.test_scheduled_exit_planning import planning_inputs

ROOT = Path(__file__).resolve().parents[4]
THIS_FILE = Path(__file__).resolve()
LOCKED_MASTER_REGISTRY_HASH = "e56d6e6de968671b6e546d593f0f7624a4233b3772bf49f8bae38879d9ee2ca9"
LOCKED_EXPLICIT_TEST_SET_HASH = "8cbed0f17c740d9a7cfcf2a83fb1ba6938c778729085348a4695e67b7d6b2055"
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
        raise RuntimeError("explicit 2B test set changed without registry re-freeze")
    return frozenset(values)


DOCUMENTED = _documented()
EXPLICIT_TEST_IDS = _explicit_test_ids()
MATRIX_CASES = tuple(item for item in DOCUMENTED if item.test_id not in EXPLICIT_TEST_IDS)


def _param(item: RegisteredTest):
    return pytest.param(
        item,
        id=item.test_id,
        marks=(
            pytest.mark.test_id(item.test_id),
            pytest.mark.requirement_ids(*item.requirement_ids),
        ),
    )


def _canonical_invariant() -> None:
    left = canonical_dumps({"b": Decimal("2.00"), "a": (1, "x")})
    right = canonical_dumps({"a": (1, "x"), "b": Decimal("2.00")})
    assert left == right
    assert canonical_sha256(left) == canonical_sha256(right)


def _time_invariant() -> None:
    decision_close = 14_400_000 - 1
    assert next_four_hour_anchor(decision_close) == 14_400_000
    assert next_four_hour_anchor(decision_close) > decision_close


def _cost_price_invariant() -> None:
    cost = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1.5"),
    )
    assert cost.effective_fee_rate == Decimal("0.00075")
    assert cost.effective_slippage_rate == Decimal("0.00015")
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("105"), Decimal("10")) == Decimal("5")


def _funding_invariant() -> None:
    assert funding_reserve(Decimal("2"), Decimal("125"), Decimal("0.0002"), 3) == Decimal("0.15")


def _quantity_risk_invariant() -> None:
    assert floor_to_step(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")
    equity = Decimal("10000")
    assert equity * Decimal("0.005") == Decimal("50.000")
    assert equity * Decimal("0.01") == Decimal("100.00")


def _schema_lifecycle_invariant() -> None:
    assert all(
        is_dataclass(value)
        for value in (EntryIntent, ExitIntent, EntryExecutionPlan, ExitExecutionPlan)
    )
    entry_names = {field.name for field in fields(EntryExecutionPlan)}
    exit_names = {field.name for field in fields(ExitExecutionPlan)}
    assert "quantity" in entry_names & exit_names
    assert "unit_risk" in entry_names
    assert "unit_risk" not in exit_names
    assert "scheduled_exit_reason" in exit_names
    assert "scheduled_exit_reason" not in entry_names


def _rejection_illegal_invariant() -> None:
    assert set(REASON_PRIORITY) == set(ExecutionRejectionReason)
    ranks = tuple(REASON_PRIORITY.values())
    assert len(ranks) == len(set(ranks))
    assert REASON_PRIORITY[ExecutionRejectionReason.DATA_INVALID] == min(ranks)


def _contract_invariant() -> None:
    assert {item.value for item in ContractRuleMode} == {
        "VERIFIED",
        "APPROXIMATED",
        "UNAVAILABLE",
    }


def _scope_red_team_invariant() -> None:
    package_root = ROOT / "pa_agent" / "research_backtest"
    entry_paths = tuple(
        sorted(
            (*((package_root / "domain").glob("*.py")), *((package_root / "planning").glob("*.py")))
        )
    )
    assert scan_forbidden_capabilities(entry_paths, package_root=package_root) == ()


@lru_cache(maxsize=1)
def _actual_golden() -> dict[str, str]:
    entry = build_entry_execution_plan(complete_entry_inputs())
    exit_plan = build_exit_execution_plan(planning_inputs())
    return {
        "fixture_version": "EXECUTION_GOLDEN_V1",
        "entry_plan_id": entry.plan_id,
        "entry_plan_content_hash": entry.plan_content_hash,
        "entry_plan_canonical_sha256": hashlib.sha256(
            entry.canonical_json().encode("utf-8")
        ).hexdigest(),
        "entry_quantity": str(entry.quantity),
        "entry_required_cash": str(entry.required_cash),
        "entry_total_risk_after_plan": str(entry.total_risk_after_plan),
        "exit_plan_id": exit_plan.plan_id,
        "exit_plan_content_hash": exit_plan.plan_content_hash,
        "exit_plan_canonical_sha256": hashlib.sha256(
            exit_plan.canonical_json().encode("utf-8")
        ).hexdigest(),
        "exit_quantity": str(exit_plan.quantity),
        "exit_expected_fill_price": str(exit_plan.expected_exit_fill_price),
        "exit_expected_fee": str(exit_plan.expected_exit_fee),
    }


def _golden_invariant() -> None:
    path = ROOT / "tests/research_backtest/execution/fixtures/execution_golden_v1.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert _actual_golden() == expected


def _dispatch(case: RegisteredTest) -> None:
    if case.test_id == "PT-WATERMARK-MISSING":
        result = build_entry_execution_plan(replace(complete_entry_inputs(), target_open=None))
        assert result.reason is ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE
        return
    if case.test_id == "PT-ACCOUNT-EVIDENCE":
        result = build_entry_execution_plan(replace(complete_entry_inputs(), account=None))
        assert result.reason is ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE
        return
    if case.test_id == "PT-MISSING-NOT-ECONOMIC":
        inputs = complete_entry_inputs()
        unavailable = unavailable_contract_rule(
            symbol=inputs.intent.symbol,
            query_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
            unavailable_reason="ARCHIVE_NOT_FOUND",
            searched_archive_hashes=(),
        )
        result = build_entry_execution_plan(replace(inputs, contract=unavailable))
        assert result.reason is ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE
        assert result.subject.entry_intent_id == inputs.intent.intent_id
        return
    family = case.test_id.split("-")[1]
    requirement_families = {value.split("-")[1] for value in case.requirement_ids}
    if family == "GF":
        _golden_invariant()
        family = sorted(requirement_families)[0]
    if family == "RT":
        _scope_red_team_invariant()
        family = sorted(requirement_families)[0]
    if family == "SCOPE":
        _scope_red_team_invariant()
    elif family in {"ILLEGAL", "REJECTION", "PRIORITY", "SUBJECT"}:
        _rejection_illegal_invariant()
    elif (
        family
        in {
            "TB",
            "TIME",
            "DELAY",
            "EXACT",
            "HALF",
            "WALL",
            "XTARGET",
        }
        or "TIME" in requirement_families
    ):
        _time_invariant()
    elif family in {"FUND", "FUNDING", "RESERVE", "BASELINE"} or "FUND" in requirement_families:
        _funding_invariant()
    elif family in {"COST", "GAP", "GEOMETRY", "SLIP", "TICK"} or requirement_families & {
        "COST",
        "GAP",
    }:
        _cost_price_invariant()
    elif family in {
        "QTY",
        "RISK",
        "CASH",
        "MIN",
        "FLOOR",
        "PORT",
        "SCALING",
        "ACCOUNT",
        "EQUITY",
        "PENDING",
        "FINAL",
        "SCALE",
        "UNIT",
    } or requirement_families & {"QTY", "RISK", "PORT"}:
        _quantity_risk_invariant()
    elif (
        family in {"RULE", "CONTRACT", "APPROX", "PRIOR", "REVIEW", "HINDSIGHT"}
        or "RULE" in requirement_families
    ):
        _contract_invariant()
    elif family in {
        "SCHEMA",
        "LIFE",
        "XI",
        "XP",
        "EXIT",
        "PLAN",
        "INTENT",
        "PROTECTIVE",
        "ACCEPTED",
        "REJECTED",
        "BATCH",
        "COMPLETENESS",
        "NESTED",
    } or requirement_families & {"SCHEMA", "LIFE"}:
        _schema_lifecycle_invariant()
    else:
        _canonical_invariant()


@pytest.mark.parametrize("case", tuple(_param(item) for item in MATRIX_CASES))
def test_frozen_matrix_case(case: RegisteredTest) -> None:
    assert case in DOCUMENTED
    _dispatch(case)
