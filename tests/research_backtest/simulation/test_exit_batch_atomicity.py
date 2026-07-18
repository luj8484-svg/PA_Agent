from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import ScheduledExitReason
from tests.research_backtest.simulation.test_entry_batch_atomicity import _plans, _state


def _opened():
    from pa_agent.research_backtest.simulation.fills import EntryBatchCommit, apply_entry_batch

    result = apply_entry_batch(_state(), _plans())
    assert isinstance(result, EntryBatchCommit)
    return result.state


def _exit_item(position, suffix: str):
    from pa_agent.research_backtest.simulation.fills import make_scheduled_exit_fill

    plan = SimpleNamespace(
        plan_id=f"exit-plan-{suffix}",
        origin_candidate_id=position.origin_candidate_id,
        position_id=position.position_id,
        symbol=position.symbol,
        position_side=position.side,
        quantity=position.quantity,
        target_execution_time_utc_ms=20_100_000,
        expected_exit_fill_price=position.entry_price + Decimal("10"),
        expected_exit_fee=Decimal("0.25"),
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
    )
    fill = make_scheduled_exit_fill(
        plan,
        (ScheduledExitReason.TIME_EXIT,),
        ScheduledExitReason.TIME_EXIT,
    )
    return position, fill


def test_two_symbol_exit_batch_is_order_invariant_and_values_once() -> None:
    from pa_agent.research_backtest.simulation.fills import ExitBatchCommit, apply_exit_batch

    state = _opened()
    items = tuple(
        _exit_item(position, str(index)) for index, position in enumerate(state.positions)
    )
    forward = apply_exit_batch(state, items, remaining_unrealized_pnl=Decimal("0"))
    reverse = apply_exit_batch(state, tuple(reversed(items)), remaining_unrealized_pnl=Decimal("0"))

    assert isinstance(forward, ExitBatchCommit)
    assert isinstance(reverse, ExitBatchCommit)
    assert canonical_sha256(forward) == canonical_sha256(reverse)
    assert forward.state.positions == ()
    assert forward.state.equity == forward.state.wallet_balance


def test_second_exit_failure_rolls_back_entire_batch() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        ExitBatchCommitFailure,
        apply_exit_batch,
    )

    state = _opened()
    first = _exit_item(state.positions[0], "btc")
    duplicate_position = replace(first[1], plan_id="different-exit-plan")
    result = apply_exit_batch(
        state,
        (first, (state.positions[0], duplicate_position)),
        remaining_unrealized_pnl=Decimal("0"),
    )
    assert isinstance(result, ExitBatchCommitFailure)
    assert result.fills == ()
    assert result.ledger_entries == ()
    assert result.trades == ()
    assert canonical_sha256(result.state) == canonical_sha256(state)
