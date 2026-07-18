from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pa_agent.research_backtest.domain.enums import ScheduledExitReason
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs


def initial_state():
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )

    config = make_simulation_config(
        symbols=("BTCUSDT", "ETHUSDT"),
        simulation_start_utc_ms=0,
        simulation_end_exit_open_utc_ms=200_040_000,
        initial_wallet_balance=Decimal("10000"),
        cost_model_version="COST_V1",
        funding_model_version="FUNDING_V1",
        two_a_version="2A_V1",
        two_b_planner_version="2B_V1",
        two_b_planner_config_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )
    return initial_engine_state(config)


def entry_plan() -> EntryExecutionPlan:
    result = build_entry_execution_plan(complete_entry_inputs())
    assert isinstance(result, EntryExecutionPlan)
    return result


def exit_plan(reason: ScheduledExitReason = ScheduledExitReason.TIME_EXIT):
    return SimpleNamespace(
        plan_id="exit-plan",
        origin_candidate_id="candidate-1",
        position_id="position-1",
        symbol="BTCUSDT",
        position_side=entry_plan().side,
        quantity=Decimal("1.234"),
        target_execution_time_utc_ms=20_100_000,
        expected_exit_fill_price=Decimal("123.4"),
        expected_exit_fee=Decimal("0.0761378"),
        scheduled_exit_reason=reason,
    )


def test_entry_fill_uses_exact_2b_price_and_geometry() -> None:
    from pa_agent.research_backtest.simulation.fills import make_entry_fill
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan

    plan = entry_plan()
    fill = make_entry_fill(plan)
    position = position_from_entry_plan(plan)
    assert fill.fill_price == plan.expected_entry_fill_price
    assert fill.fee == plan.entry_fee
    assert position.quantity == plan.quantity
    assert position.stop_trigger_price == plan.stop_trigger_price
    assert position.take_profit_trigger_price == plan.take_profit_trigger_price
    assert position.isolated_margin_balance == plan.initial_margin


def test_entry_fill_locks_cash_and_charges_fee_once() -> None:
    from pa_agent.research_backtest.simulation.fills import apply_entry_fill, make_entry_fill
    from pa_agent.research_backtest.simulation.ledger import available_balance
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan

    plan = entry_plan()
    state, entries = apply_entry_fill(
        initial_state(), make_entry_fill(plan), position_from_entry_plan(plan)
    )
    assert state.wallet_balance == Decimal("10000") - plan.entry_fee
    assert state.locked_initial_margin == plan.initial_margin
    assert state.locked_fee_reserve == plan.exit_fee_reserve
    assert state.locked_funding_reserve == plan.funding_reserve
    assert available_balance(state) == Decimal("10000") - plan.required_cash
    assert len(entries) == 4


def test_entry_plan_cannot_be_consumed_twice() -> None:
    from pa_agent.research_backtest.simulation.fills import apply_entry_fill, make_entry_fill
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan

    plan = entry_plan()
    fill = make_entry_fill(plan)
    position = position_from_entry_plan(plan)
    state, _ = apply_entry_fill(initial_state(), fill, position)
    with pytest.raises(ValueError, match="consumed"):
        apply_entry_fill(state, fill, position)


def test_one_way_symbol_rejects_second_position() -> None:
    from pa_agent.research_backtest.simulation.fills import apply_entry_fill, make_entry_fill
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan

    plan = entry_plan()
    fill = make_entry_fill(plan)
    position = position_from_entry_plan(plan)
    state, _ = apply_entry_fill(initial_state(), fill, position)
    with pytest.raises(ValueError, match="existing position"):
        apply_entry_fill(replace(state, consumed_plan_ids=()), fill, position)


def test_scheduled_exit_fill_uses_exact_2b_price_and_all_reasons() -> None:
    from pa_agent.research_backtest.simulation.fills import make_scheduled_exit_fill

    plan = exit_plan()
    fill = make_scheduled_exit_fill(
        plan,
        (ScheduledExitReason.TIME_EXIT, ScheduledExitReason.EXPERIMENT_END),
        ScheduledExitReason.TIME_EXIT,
    )
    assert fill.fill_price == plan.expected_exit_fill_price
    assert fill.fee == plan.expected_exit_fee
    assert fill.matched_exit_reasons == (
        ScheduledExitReason.TIME_EXIT,
        ScheduledExitReason.EXPERIMENT_END,
    )


def test_exit_releases_all_locks_and_realizes_pnl() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        apply_exit_fill,
        make_scheduled_exit_fill,
    )
    from pa_agent.research_backtest.simulation.positions import IsolatedPosition

    plan = exit_plan()
    position = IsolatedPosition(
        position_id=plan.position_id,
        symbol=plan.symbol,
        side=plan.position_side,
        quantity=plan.quantity,
        entry_time_utc_ms=0,
        entry_price=Decimal("100"),
        initial_margin=plan.quantity * Decimal("100"),
        isolated_margin_balance=plan.quantity * Decimal("100"),
        stop_trigger_price=Decimal("90"),
        take_profit_trigger_price=Decimal("120"),
        remaining_fee_reserve=plan.expected_exit_fee,
        remaining_funding_reserve=Decimal("2"),
        planned_funding_slice=Decimal("1"),
        remaining_funding_events=2,
        origin_plan_id="entry-plan",
        origin_candidate_id=plan.origin_candidate_id,
        maximum_exit_time_utc_ms=172_800_000,
    )
    opened = replace(
        initial_state(),
        positions=(position,),
        locked_initial_margin=position.initial_margin,
        locked_fee_reserve=position.remaining_fee_reserve,
        locked_funding_reserve=position.remaining_funding_reserve,
    )
    fill = make_scheduled_exit_fill(
        plan, (ScheduledExitReason.TIME_EXIT,), ScheduledExitReason.TIME_EXIT
    )
    closed, entries, trade = apply_exit_fill(
        opened, position, fill, remaining_unrealized_pnl=Decimal("0")
    )
    assert closed.positions == ()
    assert closed.locked_initial_margin == Decimal("0")
    assert closed.locked_fee_reserve == Decimal("0")
    assert closed.locked_funding_reserve == Decimal("0")
    assert trade.net_pnl == trade.gross_pnl - trade.entry_fee - trade.exit_fee + trade.funding
    assert len(entries) == 5


def test_profitable_exit_does_not_double_count_stale_unrealized_in_peak() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        apply_exit_fill,
        make_scheduled_exit_fill,
    )
    from pa_agent.research_backtest.simulation.positions import IsolatedPosition

    plan = exit_plan()
    position = IsolatedPosition(
        position_id=plan.position_id,
        symbol=plan.symbol,
        side=plan.position_side,
        quantity=plan.quantity,
        entry_time_utc_ms=0,
        entry_price=Decimal("100"),
        initial_margin=plan.quantity * Decimal("100"),
        isolated_margin_balance=plan.quantity * Decimal("100"),
        stop_trigger_price=Decimal("90"),
        take_profit_trigger_price=Decimal("120"),
        remaining_fee_reserve=plan.expected_exit_fee,
        remaining_funding_reserve=Decimal("2"),
        planned_funding_slice=Decimal("1"),
        remaining_funding_events=2,
        origin_plan_id="entry-plan",
        origin_candidate_id=plan.origin_candidate_id,
        maximum_exit_time_utc_ms=172_800_000,
    )
    opened = replace(
        initial_state(),
        positions=(position,),
        locked_initial_margin=position.initial_margin,
        locked_fee_reserve=position.remaining_fee_reserve,
        locked_funding_reserve=position.remaining_funding_reserve,
        unrealized_pnl=Decimal("28.8756"),
        equity=Decimal("10028.8756"),
        peak_equity=Decimal("10028.8756"),
    )
    fill = make_scheduled_exit_fill(
        plan, (ScheduledExitReason.TIME_EXIT,), ScheduledExitReason.TIME_EXIT
    )
    closed, _, _ = apply_exit_fill(opened, position, fill, remaining_unrealized_pnl=Decimal("0"))
    assert closed.equity == closed.wallet_balance
    assert closed.peak_equity == opened.peak_equity


def test_partial_exit_preserves_remaining_position_unrealized_and_peak() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        apply_exit_fill,
        make_scheduled_exit_fill,
    )
    from pa_agent.research_backtest.simulation.positions import IsolatedPosition

    plan = exit_plan()
    btc = IsolatedPosition(
        position_id=plan.position_id,
        symbol="BTCUSDT",
        side=plan.position_side,
        quantity=plan.quantity,
        entry_time_utc_ms=0,
        entry_price=Decimal("100"),
        initial_margin=plan.quantity * Decimal("100"),
        isolated_margin_balance=plan.quantity * Decimal("100"),
        stop_trigger_price=Decimal("90"),
        take_profit_trigger_price=Decimal("120"),
        remaining_fee_reserve=plan.expected_exit_fee,
        remaining_funding_reserve=Decimal("2"),
        planned_funding_slice=Decimal("1"),
        remaining_funding_events=2,
        origin_plan_id="entry-plan",
        origin_candidate_id=plan.origin_candidate_id,
        maximum_exit_time_utc_ms=172_800_000,
    )
    eth = replace(
        btc,
        position_id="position-eth",
        symbol="ETHUSDT",
        origin_plan_id="entry-plan-eth",
    )
    remaining_unrealized = Decimal("-50")
    opened = replace(
        initial_state(),
        positions=(btc, eth),
        locked_initial_margin=btc.initial_margin + eth.initial_margin,
        locked_fee_reserve=btc.remaining_fee_reserve + eth.remaining_fee_reserve,
        locked_funding_reserve=btc.remaining_funding_reserve + eth.remaining_funding_reserve,
        unrealized_pnl=Decimal("-25"),
        equity=Decimal("9975"),
        peak_equity=Decimal("10000"),
    )
    fill = make_scheduled_exit_fill(
        plan, (ScheduledExitReason.TIME_EXIT,), ScheduledExitReason.TIME_EXIT
    )
    closed, _, _ = apply_exit_fill(
        opened,
        btc,
        fill,
        remaining_unrealized_pnl=remaining_unrealized,
    )
    assert closed.positions == (eth,)
    assert closed.unrealized_pnl == remaining_unrealized
    assert closed.equity == closed.wallet_balance + remaining_unrealized
    assert closed.peak_equity == opened.peak_equity


def test_stable_entry_batch_order() -> None:
    from pa_agent.research_backtest.simulation.fills import stable_entry_plan_order

    btc = SimpleNamespace(symbol="BTCUSDT", plan_id="a")
    eth = SimpleNamespace(symbol="ETHUSDT", plan_id="z")
    btc_late = SimpleNamespace(symbol="BTCUSDT", plan_id="y")
    assert stable_entry_plan_order((eth, btc_late, btc)) == (btc, btc_late, eth)
