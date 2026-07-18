from dataclasses import replace
from decimal import Decimal

from pa_agent.research_backtest.domain.canonical import canonical_dumps
from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs


def _state(wallet: Decimal = Decimal("10000")):
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )

    config = make_simulation_config(
        symbols=("BTCUSDT", "ETHUSDT"),
        simulation_start_utc_ms=0,
        simulation_end_exit_open_utc_ms=60_000,
        initial_wallet_balance=Decimal("10000"),
        cost_model_version="COST_V1",
        funding_model_version="FUNDING_V1",
        two_a_version="2A_V1",
        two_b_planner_version="2B_V1",
        two_b_planner_config_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )
    state = initial_engine_state(config)
    return replace(state, wallet_balance=wallet, equity=wallet, peak_equity=wallet)


def _plans():
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )

    plans = build_entry_batch_planning_outcome(_batch_inputs()).plans
    assert tuple(item.symbol for item in plans) == ("BTCUSDT", "ETHUSDT")
    return plans


def test_valid_btc_eth_entry_batch_commits_all_at_once() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        EntryBatchCommit,
        apply_entry_batch,
    )

    result = apply_entry_batch(_state(), _plans())
    assert isinstance(result, EntryBatchCommit)
    assert tuple(item.symbol for item in result.fills) == ("BTCUSDT", "ETHUSDT")
    assert tuple(item.symbol for item in result.state.positions) == ("BTCUSDT", "ETHUSDT")
    assert len(result.ledger_entries) == 8


def test_second_plan_insufficient_balance_rolls_back_entire_batch() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        EntryBatchCommitFailure,
        apply_entry_batch,
    )

    plans = _plans()
    wallet = plans[0].required_cash + plans[1].required_cash - Decimal("0.00000001")
    original = _state(wallet)
    before = canonical_dumps(original)
    result = apply_entry_batch(original, plans)
    assert isinstance(result, EntryBatchCommitFailure)
    assert result.reason == "ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION"
    assert result.fills == ()
    assert result.ledger_entries == ()
    assert canonical_dumps(original) == before


def test_duplicate_second_plan_id_and_symbol_rolls_back_entire_batch() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        EntryBatchCommitFailure,
        apply_entry_batch,
    )

    first = _plans()[0]
    original = _state()
    before = canonical_dumps(original)
    result = apply_entry_batch(original, (first, first))
    assert isinstance(result, EntryBatchCommitFailure)
    assert result.fills == ()
    assert result.ledger_entries == ()
    assert canonical_dumps(original) == before


def test_existing_symbol_position_rolls_back_entire_batch() -> None:
    from pa_agent.research_backtest.simulation.fills import (
        EntryBatchCommit,
        EntryBatchCommitFailure,
        apply_entry_batch,
    )

    plans = _plans()
    opened = apply_entry_batch(_state(), (plans[0],))
    assert isinstance(opened, EntryBatchCommit)
    before = canonical_dumps(opened.state)
    result = apply_entry_batch(opened.state, plans)
    assert isinstance(result, EntryBatchCommitFailure)
    assert result.fills == ()
    assert result.ledger_entries == ()
    assert canonical_dumps(opened.state) == before
