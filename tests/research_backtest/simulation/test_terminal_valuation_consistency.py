from dataclasses import replace
from decimal import Decimal

import pytest

from tests.research_backtest.simulation.test_entry_batch_atomicity import _state
from tests.research_backtest.simulation.test_ledger_account import entry


def test_ledger_mutation_requires_explicit_valuation_commit_before_external_use() -> None:
    from pa_agent.research_backtest.simulation.ledger import (
        AccountInvariantError,
        assert_account_snapshot_consistent,
        commit_valuation,
        reduce_ledger,
    )

    previous = replace(
        _state(),
        unrealized_pnl=Decimal("25"),
        equity=Decimal("10025"),
        peak_equity=Decimal("10025"),
    )
    mutated = reduce_ledger(previous, (entry("FUNDING", "10", "funding-income"),))
    with pytest.raises(AccountInvariantError, match="equity"):
        assert_account_snapshot_consistent(mutated)
    committed = commit_valuation(mutated, Decimal("25"))
    assert_account_snapshot_consistent(committed)
    assert committed.equity == committed.wallet_balance + committed.unrealized_pnl


def test_halt_then_invalid_path_result_keeps_entry_disabled() -> None:
    from pa_agent.research_backtest.simulation.domain import PathState
    from pa_agent.research_backtest.simulation.output import PathResult

    state = replace(
        _state(),
        path_state=PathState.INVALID,
        halt_trigger_time_utc_ms=60_000,
        halt_reason="CLOSE_DRAWDOWN_10_PERCENT",
    )
    result = PathResult(
        path_state=state.path_state,
        final_processed_time_utc_ms=120_000,
        halt_trigger_time_utc_ms=state.halt_trigger_time_utc_ms,
        halt_reason=state.halt_reason,
        entry_disabled=state.halt_trigger_time_utc_ms is not None,
    )
    assert result.entry_disabled is True


def test_funding_then_missing_maintenance_evidence_returns_consistent_invalid_state() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import FundingRecord
    from pa_agent.research_backtest.simulation.ledger import assert_account_snapshot_consistent
    from tests.research_backtest.simulation.test_funding_liquidation import position
    from tests.research_backtest.simulation.test_minute_engine_output import (
        config,
        dependencies,
        minute,
    )

    pos = position()
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    funding = FundingRecord(
        "funding-before-invalid",
        pos.symbol,
        60_000,
        Decimal("0.01"),
        Decimal("100"),
        "a" * 64,
    )
    value = replace(minute(), funding_records=(funding,), funding_expected=True)
    result = process_minute(
        state,
        value,
        config(),
        dependencies(
            maintenance_evidence_factory=lambda *_: (_ for _ in ()).throw(
                ValueError("missing maintenance evidence")
            )
        ),
    )

    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[-1].reason == "MAINTENANCE_EVIDENCE_UNAVAILABLE"
    assert result.state.wallet_balance == Decimal("9998")
    assert result.state.equity == result.state.wallet_balance + result.state.unrealized_pnl
    assert_account_snapshot_consistent(result.state)


def test_entry_fill_then_intraminute_evidence_failure_returns_consistent_invalid_state() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.ledger import assert_account_snapshot_consistent
    from pa_agent.research_backtest.simulation.planning import (
        PlannerDependencies,
        build_entry_batch_planning_outcome,
    )
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs
    from tests.research_backtest.simulation.test_minute_engine_output import (
        config,
        dependencies,
        minute,
    )

    batch_inputs = _batch_inputs()
    outcome = build_entry_batch_planning_outcome(batch_inputs)
    due = tuple(item.intent for item in batch_inputs.items)
    cfg = config(simulation_end_exit_open_utc_ms=TARGET_TIME + 60_000)
    state = replace(initial_engine_state(cfg), pending_entry_intents=due)
    value = minute(TARGET_TIME)
    value = replace(
        value,
        trade_bars=(
            *value.trade_bars,
            replace(value.trade_bars[0], symbol="ETHUSDT"),
        ),
        mark_bars=(
            *value.mark_bars,
            replace(value.mark_bars[0], symbol="ETHUSDT"),
        ),
    )
    result = process_minute(
        state,
        value,
        cfg,
        dependencies(
            planners=PlannerDependencies(
                lambda *_: batch_inputs,
                lambda _: outcome,
                None,
                None,
            ),
            maintenance_evidence_factory=lambda *_: (_ for _ in ()).throw(
                ValueError("missing intraminute maintenance evidence")
            ),
        ),
    )

    assert result.state.path_state.value == "INVALID"
    assert result.fills
    assert result.planning_outputs[-1].reason == "MAINTENANCE_EVIDENCE_UNAVAILABLE"
    assert result.state.equity == result.state.wallet_balance + result.state.unrealized_pnl
    assert_account_snapshot_consistent(result.state)
