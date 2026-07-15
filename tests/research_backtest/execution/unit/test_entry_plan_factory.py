from __future__ import annotations

from dataclasses import fields, replace

import pytest

from pa_agent.research_backtest.domain.contracts import unavailable_contract_rule
from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, ExperimentState
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from tests.research_backtest.execution.fixtures.entry_plan_case import (
    MAXIMUM_EXIT_TIME,
    TARGET_TIME,
    complete_entry_inputs,
)


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        return pytest.mark.test_id(test_id)(pytest.mark.requirement_ids(requirement_id)(function))

    return decorate


@registered("UT-LIFE-003", "2B-LIFE-003")
def test_final_entry_plan_is_built_only_after_scaling() -> None:
    inputs = complete_entry_inputs()
    plan = build_entry_execution_plan(inputs)
    assert isinstance(plan, EntryExecutionPlan)
    assert plan.quantity == inputs.accepted_item.final_quantity
    assert plan.portfolio_scaling_result_id == inputs.scaling.result_id
    assert plan.accepted_scaling_item_id == inputs.accepted_item.item_id
    assert (
        build_entry_execution_plan(replace(inputs, cost=None)).reason
        is ExecutionRejectionReason.COST_MODEL_UNAVAILABLE
    )
    assert (
        build_entry_execution_plan(replace(inputs, open_risk_evidence_records=None)).reason
        is ExecutionRejectionReason.OPEN_RISK_MODEL_UNAVAILABLE
    )


@registered("UT-SCHEMA-002", "2B-SCHEMA-002")
def test_entry_plan_is_a_closed_entry_only_schema() -> None:
    plan = build_entry_execution_plan(complete_entry_inputs())
    names = {item.name for item in fields(type(plan))}
    assert {"scheduled_exit_reason", "position_id", "fill_id"}.isdisjoint(names)
    assert {"entry_fee", "exit_fee_reserve", "funding_reserve", "required_cash"} <= names


@registered("UT-LIFE-010", "2B-LIFE-010")
def test_plan_formulas_and_evidence_links_are_exact() -> None:
    inputs = complete_entry_inputs()
    plan = build_entry_execution_plan(inputs)
    assert plan.plan_created_time_utc_ms == TARGET_TIME
    assert plan.maximum_exit_time_utc_ms == MAXIMUM_EXIT_TIME
    assert plan.target_minute_input_hash == inputs.target_open.snapshot_content_hash
    assert plan.reference_price == inputs.target_open.open_price
    assert plan.notional == plan.quantity * plan.expected_entry_fill_price
    assert plan.required_cash == (
        plan.initial_margin + plan.entry_fee + plan.exit_fee_reserve + plan.funding_reserve
    )


@registered("UT-LIFE-008", "2B-LIFE-008")
def test_halted_experiment_rejects_new_entry_plan() -> None:
    rejection = build_entry_execution_plan(complete_entry_inputs(state=ExperimentState.HALTED))
    assert rejection.reason.value == "EXPERIMENT_HALTED"


@registered("UT-LIFE-006", "2B-LIFE-006")
def test_entry_plan_factory_is_pure_and_plan_identity_self_validates() -> None:
    inputs = complete_entry_inputs()
    before = (inputs.intent.canonical_json(), inputs.account.canonical_json())
    first = build_entry_execution_plan(inputs)
    second = build_entry_execution_plan(inputs)
    assert first == second
    assert before == (inputs.intent.canonical_json(), inputs.account.canonical_json())
    with pytest.raises(ValueError, match="Canonical content"):
        replace(first, plan_id="eplan_" + "0" * 24)


def _corrupt_frozen(value, **changes):
    forged = object.__new__(type(value))
    for field in fields(type(value)):
        object.__setattr__(forged, field.name, changes.get(field.name, getattr(value, field.name)))
    return forged


@registered("UT-RT-051", "2B-RISK-011")
def test_equity_must_replay_from_the_supplied_account_evidence() -> None:
    inputs = complete_entry_inputs()
    forged = _corrupt_frozen(inputs.account, current_equity=inputs.account.current_equity + 1)
    result = build_entry_execution_plan(replace(inputs, account=forged))
    assert result.reason is ExecutionRejectionReason.DATA_INVALID
    unavailable = unavailable_contract_rule(
        symbol=inputs.intent.symbol,
        query_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    multi = build_entry_execution_plan(
        replace(inputs, account=forged, contract=unavailable, target_open=None)
    )
    assert multi.reason is ExecutionRejectionReason.DATA_INVALID
    forged_candidate = _corrupt_frozen(inputs.candidate, symbol="ETHUSDT")
    result = build_entry_execution_plan(
        replace(inputs, candidate=forged_candidate, contract=unavailable)
    )
    assert result.reason is ExecutionRejectionReason.DATA_INVALID


@registered("UT-RT-052", "2B-RISK-012")
def test_risk_aggregates_must_replay_from_the_supplied_account_evidence() -> None:
    inputs = complete_entry_inputs()
    forged = _corrupt_frozen(
        inputs.account, existing_open_risk=inputs.account.existing_open_risk + 1
    )
    result = build_entry_execution_plan(replace(inputs, account=forged))
    assert result.reason is ExecutionRejectionReason.DATA_INVALID
