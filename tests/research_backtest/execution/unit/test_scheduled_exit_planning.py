from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.contracts import (
    unavailable_contract_rule,
    verified_contract_rule,
)
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ResearchStage,
    ScheduledExitReason,
    Side,
)
from pa_agent.research_backtest.domain.intents import exit_condition_snapshot
from pa_agent.research_backtest.domain.market_inputs import (
    target_event_watermark,
    target_minute_open_snapshot,
)
from pa_agent.research_backtest.domain.plans import ExitExecutionPlan
from pa_agent.research_backtest.planning.exits import (
    ExitPlanningInputs,
    build_exit_execution_plan,
    make_exit_intent,
)

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
CONDITION_TIME = 20_000_123
ANCHOR = 20_040_000
TARGET = 20_100_000


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        return pytest.mark.test_id(test_id)(pytest.mark.requirement_ids(requirement_id)(function))

    return decorate


def condition(reason: ScheduledExitReason = ScheduledExitReason.TIME_EXIT):
    return exit_condition_snapshot(
        origin_candidate_id="cand_" + "1" * 24,
        position_id="position-1",
        position_snapshot_hash=SHA,
        symbol="BTCUSDT",
        position_side=Side.LONG,
        exit_quantity=Decimal("1.234"),
        scheduled_exit_reason=reason,
        condition_time_utc_ms=CONDITION_TIME,
        condition_visible_input_hash="d" * 64,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


def intent(reason: ScheduledExitReason = ScheduledExitReason.TIME_EXIT):
    return make_exit_intent(
        condition(reason),
        execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
        computational_experiment_id="e" * 64,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


def planning_inputs(
    reason: ScheduledExitReason = ScheduledExitReason.TIME_EXIT,
    *,
    step_size: Decimal = Decimal("0.001"),
):
    value = intent(reason)
    target_open = target_minute_open_snapshot(
        symbol="BTCUSDT",
        open_time_utc_ms=TARGET,
        open_price=Decimal("123.45"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    watermark = target_event_watermark(
        symbol="BTCUSDT",
        target_open_time_utc_ms=TARGET,
        event_watermark_time_utc_ms=TARGET,
        watermark_source_event_id="exit-watermark-event",
        watermark_source_stream_version="BINANCE_TRADE_WATERMARK_V1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    contract = verified_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET,
        source_kind="BINANCE_ARCHIVE",
        source_uri_or_archive_id="rules/btc/v1",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=TARGET + 1,
        rule_version="BTCUSDT_RULE_V1",
        tick_size=Decimal("0.1"),
        step_size=step_size,
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="f" * 64,
    )
    cost = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1"),
    )
    return ExitPlanningInputs(
        intent=value,
        target_open=target_open,
        watermark=watermark,
        contract=contract,
        cost=cost,
        target_position_snapshot_hash=SHA,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
        stage=ResearchStage.BACKTEST,
    )


@registered("UT-LIFE-004", "2B-LIFE-004")
def test_only_four_scheduled_reasons_create_exit_intents() -> None:
    for reason in ScheduledExitReason:
        value = intent(reason)
        assert value.scheduled_exit_reason is reason
        assert value.execution_anchor_utc_ms == ANCHOR
        assert value.target_execution_time_utc_ms == TARGET


@registered("UT-SCHEMA-003", "2B-SCHEMA-003")
def test_exit_intent_contains_no_future_price_or_contract_fields() -> None:
    names = {item.name for item in fields(type(intent()))}
    assert not any(
        token in name for name in names for token in ("price", "contract", "fee", "target_open")
    )


@registered("UT-LIFE-005", "2B-LIFE-005")
def test_exit_plan_waits_for_target_and_allows_halt_exit() -> None:
    inputs = planning_inputs(ScheduledExitReason.HALT_EXIT)
    plan = build_exit_execution_plan(inputs)
    assert isinstance(plan, ExitExecutionPlan)
    assert plan.scheduled_exit_reason is ScheduledExitReason.HALT_EXIT
    assert plan.quantity == Decimal("1.234")
    assert plan.plan_created_time_utc_ms == TARGET
    assert (
        build_exit_execution_plan(replace(inputs, cost=None)).reason
        is ExecutionRejectionReason.COST_MODEL_UNAVAILABLE
    )
    unavailable = unavailable_contract_rule(
        symbol=inputs.intent.symbol,
        query_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    multi = build_exit_execution_plan(
        replace(inputs, contract=unavailable, target_position_snapshot_hash="8" * 64)
    )
    assert multi.reason is ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE


@registered("UT-SCHEMA-004", "2B-SCHEMA-004")
def test_exit_plan_has_no_entry_risk_or_protective_trigger_fields() -> None:
    plan = build_exit_execution_plan(planning_inputs())
    names = {item.name for item in fields(type(plan))}
    forbidden = {
        "entry_fee",
        "exit_fee_reserve",
        "funding_reserve",
        "initial_margin",
        "unit_risk",
        "single_risk_budget",
        "stop_trigger_price",
        "take_profit_trigger_price",
        "portfolio_scaling_result_id",
    }
    assert names.isdisjoint(forbidden)


@registered("UT-LIFE-011", "2B-LIFE-011")
def test_changed_position_and_rule_rollover_mismatch_are_rejected() -> None:
    changed = build_exit_execution_plan(
        replace(planning_inputs(), target_position_snapshot_hash="0" * 64)
    )
    assert changed.reason.value == "POSITION_SNAPSHOT_CHANGED"
    misaligned = build_exit_execution_plan(planning_inputs(step_size=Decimal("0.01")))
    assert misaligned.reason.value == "POSITION_QUANTITY_RULE_MISMATCH"
