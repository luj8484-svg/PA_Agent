from __future__ import annotations

import importlib
import inspect
import re
import tempfile
from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.batches import expected_intent_ref
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, ResearchStage
from pa_agent.research_backtest.domain.rejections import entry_intent_subject_ref_from_identity
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from pa_agent.research_backtest.testing.registry import (
    RegisteredTest,
    default_document_paths,
    load_documented_master_registry,
)
from pa_agent.research_backtest.testing.scope import scan_forbidden_capabilities
from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs
from tests.research_backtest.execution.unit.test_batch_scaling import (
    COMMIT as BATCH_COMMIT,
)
from tests.research_backtest.execution.unit.test_batch_scaling import LOCK as BATCH_LOCK
from tests.research_backtest.execution.unit.test_batch_scaling import TIME as BATCH_TIME
from tests.research_backtest.execution.unit.test_batch_scaling import complete as complete_batch
from tests.research_backtest.execution.unit.test_scheduled_exit_planning import planning_inputs

ROOT = Path(__file__).resolve().parents[4]
THIS_FILE = Path(__file__).resolve()
SCENARIO_PATH = (
    ROOT / "tests" / "research_backtest" / "execution" / "fixtures" / "frozen_case_scenarios_v1.tsv"
)
LOCKED_MASTER_REGISTRY_HASH = "e56d6e6de968671b6e546d593f0f7624a4233b3772bf49f8bae38879d9ee2ca9"
LOCKED_EXPLICIT_TEST_SET_HASH = "d9955f044a13f365598a39586220f14208d3842ea950de6beb07b7a10eaad3bc"
EXPLICIT_ID_PATTERN = re.compile(r'(?:registered|test_id)\("([A-Z0-9-]+)"')
SEMANTIC_CASE_SCHEMA_VERSION = "FROZEN_SEMANTIC_CASE_V1"
LOCAL_CONTRACT_MODULE = "tests.research_backtest.execution.acceptance.test_frozen_matrix_generated"
UNIT_CONTRACT_MODULES = (
    "tests.research_backtest.execution.unit.test_account_evidence",
    "tests.research_backtest.execution.unit.test_batch_scaling",
    "tests.research_backtest.execution.unit.test_contract_cost_funding",
    "tests.research_backtest.execution.unit.test_entry_intent_time_market",
    "tests.research_backtest.execution.unit.test_entry_plan_factory",
    "tests.research_backtest.execution.unit.test_price_gap_sizing",
    "tests.research_backtest.execution.unit.test_registry_canonical_scope",
    "tests.research_backtest.execution.unit.test_rejection_matrix",
    "tests.research_backtest.execution.unit.test_scheduled_exit_planning",
)


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


def _semantic_scope_boundary() -> None:
    package_root = ROOT / "pa_agent" / "research_backtest"
    paths = tuple(
        sorted(
            (*((package_root / "domain").glob("*.py")), *((package_root / "planning").glob("*.py")))
        )
    )
    assert scan_forbidden_capabilities(paths, package_root=package_root) == ()


def _semantic_exit_and_holding_time() -> None:
    exit_value = planning_inputs().intent
    assert exit_value.target_execution_time_utc_ms > exit_value.condition_time_utc_ms
    entry_value = build_entry_execution_plan(complete_entry_inputs())
    assert (
        entry_value.maximum_exit_time_utc_ms - entry_value.target_execution_time_utc_ms
        == 172_800_000
    )


def _semantic_split_boundary() -> None:
    inputs = complete_entry_inputs()
    baseline = build_entry_execution_plan(inputs)
    wider = build_entry_execution_plan(
        replace(inputs, split_end_utc_ms=inputs.split_end_utc_ms + 1)
    )
    assert wider.plan_id == baseline.plan_id
    invalid = build_entry_execution_plan(
        replace(inputs, split_end_utc_ms=inputs.intent.target_execution_time_utc_ms)
    )
    assert invalid.reason is ExecutionRejectionReason.DATA_INVALID


def _semantic_incomplete_pre_batch() -> None:
    from pa_agent.research_backtest.planning.portfolio import resolve_batch_completeness

    expected = (
        expected_intent_ref("eint_" + "1" * 24, "BTCUSDT", BATCH_TIME),
        expected_intent_ref("eint_" + "2" * 24, "ETHUSDT", BATCH_TIME),
    )
    subject = entry_intent_subject_ref_from_identity(
        entry_intent_id=expected[0].entry_intent_id,
        candidate_id="cand_" + "1" * 24,
        symbol="BTCUSDT",
        intent_content_hash="a" * 64,
    )
    result = resolve_batch_completeness(
        expected,
        (),
        subject=subject,
        completeness_event_time_utc_ms=BATCH_TIME,
        source_event_id="semantic-incomplete-event",
        stage=ResearchStage.BACKTEST,
        code_commit=BATCH_COMMIT,
        dependency_lock_hash=BATCH_LOCK,
    )
    assert result.reason is ExecutionRejectionReason.BATCH_INCOMPLETE
    assert type(result.subject).__name__ == "EntryIntentSubjectRef"


def _semantic_portfolio_identity_and_risk() -> None:
    from pa_agent.research_backtest.planning.portfolio import scale_portfolio

    args = complete_batch(balance=Decimal("1000"))
    result = scale_portfolio(*args)
    assert result.portfolio_planning_batch_id == args[0].batch_id
    assert result.ordered_input_result_ids == args[0].ordered_successful_sizing_result_ids
    assert len({item.item_id for item in result.item_results}) == len(result.item_results)
    assert Decimal("0") <= result.final_scale <= Decimal("1")


def _semantic_closed_batch_scaling_schemas() -> None:
    batch, *_ = complete_batch()
    assert batch.completeness_snapshot_id.startswith("bcomplete_")
    assert batch.ordered_resolution_refs
    assert set(batch.ordered_successful_sizing_result_ids) <= {
        item.resolution_object_id for item in batch.ordered_resolution_refs
    }
    assert "item_input_hash" not in {field.name for field in fields(type(batch))}


def _semantic_entry_lifecycle_links() -> None:
    inputs = complete_entry_inputs()
    plan = build_entry_execution_plan(inputs)
    assert plan.intent_id == inputs.intent.intent_id
    assert plan.portfolio_planning_batch_id == inputs.batch.batch_id
    assert plan.portfolio_scaling_result_id == inputs.scaling.result_id
    assert plan.accepted_scaling_item_id == inputs.accepted_item.item_id
    assert {"fill_id", "position_id"}.isdisjoint(field.name for field in fields(type(plan)))


LOCAL_SEMANTIC_CONTRACTS = {
    "2B-LIFE-007": _semantic_entry_lifecycle_links,
    "2B-LIFE-009": _semantic_entry_lifecycle_links,
    "2B-PORT-006": _semantic_portfolio_identity_and_risk,
    "2B-PORT-007": _semantic_incomplete_pre_batch,
    "2B-RISK-005": _semantic_portfolio_identity_and_risk,
    "2B-RISK-008": _semantic_portfolio_identity_and_risk,
    "2B-SCHEMA-008": _semantic_closed_batch_scaling_schemas,
    "2B-SCHEMA-010": _semantic_closed_batch_scaling_schemas,
    "2B-SCHEMA-011": _semantic_closed_batch_scaling_schemas,
    "2B-SCOPE-001": _semantic_scope_boundary,
    "2B-SCOPE-002": _semantic_scope_boundary,
    "2B-SCOPE-003": _semantic_scope_boundary,
    "2B-SCOPE-004": _semantic_scope_boundary,
    "2B-SCOPE-005": _semantic_scope_boundary,
    "2B-TIME-003": _semantic_exit_and_holding_time,
    "2B-TIME-004": _semantic_exit_and_holding_time,
    "2B-TIME-006": _semantic_split_boundary,
    "2B-TIME-011": _semantic_incomplete_pre_batch,
}


def _semantic_contract_index() -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for module_name in UNIT_CONTRACT_MODULES:
        module = importlib.import_module(module_name)
        for function_name, function in inspect.getmembers(module, inspect.isfunction):
            marks = getattr(function, "pytestmark", ())
            requirements = tuple(
                requirement
                for mark in marks
                if mark.name == "requirement_ids"
                for requirement in mark.args
            )
            test_ids = tuple(
                test_id for mark in marks if mark.name == "test_id" for test_id in mark.args
            )
            if not requirements or len(test_ids) != 1:
                continue
            if any(name != "tmp_path" for name in inspect.signature(function).parameters):
                raise RuntimeError(
                    f"unsupported semantic contract fixture: {module_name}:{function_name}"
                )
            case_name = f"{module_name}:{function_name}"
            for requirement in requirements:
                values.setdefault(requirement, []).append(case_name)
    for requirement, function in LOCAL_SEMANTIC_CONTRACTS.items():
        values.setdefault(requirement, []).append(f"{LOCAL_CONTRACT_MODULE}:{function.__name__}")
    missing = {
        requirement
        for item in DOCUMENTED
        for requirement in item.requirement_ids
        if requirement not in values
    }
    if missing:
        raise RuntimeError(f"requirements without executable semantic contracts: {sorted(missing)}")
    return {key: tuple(sorted(set(items))) for key, items in values.items()}


SEMANTIC_CONTRACTS = _semantic_contract_index()


def semantic_case_names(requirement_ids: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                case_name
                for requirement in requirement_ids
                for case_name in SEMANTIC_CONTRACTS[requirement]
            }
        )
    )


def _execute_semantic_cases(case_names: tuple[str, ...]) -> tuple[str, ...]:
    for case_name in case_names:
        module_name, function_name = case_name.split(":", 1)
        function = (
            globals()[function_name]
            if module_name == LOCAL_CONTRACT_MODULE
            else getattr(importlib.import_module(module_name), function_name)
        )
        if "tmp_path" in inspect.signature(function).parameters:
            with tempfile.TemporaryDirectory(prefix="pa-2b-semantic-") as directory:
                function(Path(directory))
        else:
            function()
    return case_names


def _load_scenarios() -> dict[str, dict[str, object]]:
    lines = SCENARIO_PATH.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != (
        "test_id\trequirement_ids\tsemantic_cases\tsemantic_contract_hash"
    ):
        raise RuntimeError("unsupported frozen semantic-case schema")
    result: dict[str, dict[str, object]] = {}
    for line in lines[1:]:
        test_id, requirement_ids, semantic_cases, semantic_contract_hash = line.split("\t")
        if test_id in result:
            raise RuntimeError(f"duplicate frozen semantic case: {test_id}")
        result[test_id] = {
            "test_id": test_id,
            "requirement_ids": tuple(requirement_ids.split(",")),
            "semantic_cases": tuple(semantic_cases.split("|")),
            "semantic_contract_hash": semantic_contract_hash,
        }
    return result


SCENARIOS = _load_scenarios()
EXPECTED_MATRIX_IDS = {item.test_id for item in MATRIX_CASES}
if set(SCENARIOS) != EXPECTED_MATRIX_IDS:
    raise RuntimeError("every generated test ID requires exactly one frozen semantic case")


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
    expected_semantic_cases = semantic_case_names(case.requirement_ids)
    assert record["requirement_ids"] == case.requirement_ids
    assert record["semantic_cases"] == expected_semantic_cases
    assert record["semantic_contract_hash"] == canonical_sha256(
        {
            "test_id": case.test_id,
            "requirement_ids": case.requirement_ids,
            "semantic_cases": expected_semantic_cases,
            "schema_version": SEMANTIC_CASE_SCHEMA_VERSION,
        }
    )
    assert _execute_semantic_cases(expected_semantic_cases) == expected_semantic_cases
