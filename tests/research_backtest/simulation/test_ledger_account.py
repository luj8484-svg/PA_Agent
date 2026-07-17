from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st


def state():
    from pa_agent.research_backtest.simulation.domain import EngineState, PathKind, PathState

    z = Decimal("0")
    return EngineState(
        path_kind=PathKind.BASELINE,
        path_state=PathState.VALID,
        wallet_balance=Decimal("10000"),
        locked_initial_margin=z,
        locked_fee_reserve=z,
        locked_funding_reserve=z,
        pending_plan_reserve=z,
        unrealized_pnl=z,
        equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        positions=(),
        consumed_plan_ids=(),
        consumed_funding_ids=(),
        consumed_close_ids=(),
        consumed_ledger_ids=(),
        halt_trigger_time_utc_ms=None,
        halt_reason=None,
        flat_after_halt_time_utc_ms=None,
        final_processed_time_utc_ms=None,
    )


def entry(kind: str, amount: str, ident: str = "one"):
    from pa_agent.research_backtest.simulation.ledger import LedgerEntry, LedgerKind

    value = Decimal(amount)
    kwargs = {
        "entry_id": ident,
        "event_time_utc_ms": 60_000,
        "kind": LedgerKind(kind),
        "wallet_delta": Decimal("0"),
        "initial_margin_delta": Decimal("0"),
        "fee_reserve_delta": Decimal("0"),
        "funding_reserve_delta": Decimal("0"),
        "pending_plan_reserve_delta": Decimal("0"),
    }
    field = {
        "ENTRY_FEE": "wallet_delta",
        "EXIT_FEE": "wallet_delta",
        "FUNDING": "wallet_delta",
        "REALIZED_PNL": "wallet_delta",
        "MARGIN_LOCK": "initial_margin_delta",
        "MARGIN_RELEASE": "initial_margin_delta",
        "FEE_RESERVE_LOCK": "fee_reserve_delta",
        "FEE_RESERVE_RELEASE": "fee_reserve_delta",
        "FUNDING_RESERVE_LOCK": "funding_reserve_delta",
        "FUNDING_RESERVE_RELEASE": "funding_reserve_delta",
        "PENDING_PLAN_RESERVE_LOCK": "pending_plan_reserve_delta",
        "PENDING_PLAN_RESERVE_RELEASE": "pending_plan_reserve_delta",
    }[kind]
    kwargs[field] = value
    return LedgerEntry(**kwargs)


def test_fee_changes_wallet_once() -> None:
    from pa_agent.research_backtest.simulation.ledger import reduce_ledger

    result = reduce_ledger(state(), (entry("ENTRY_FEE", "-10"),))
    assert result.wallet_balance == Decimal("9990")
    assert result.equity == Decimal("9990")


def test_margin_lock_changes_available_not_wallet() -> None:
    from pa_agent.research_backtest.simulation.ledger import available_balance, reduce_ledger

    result = reduce_ledger(state(), (entry("MARGIN_LOCK", "1000"),))
    assert result.wallet_balance == Decimal("10000")
    assert result.locked_initial_margin == Decimal("1000")
    assert available_balance(result) == Decimal("9000")


def test_reserve_release_is_not_income() -> None:
    from pa_agent.research_backtest.simulation.ledger import reduce_ledger

    locked = reduce_ledger(state(), (entry("FUNDING_RESERVE_LOCK", "20", "lock"),))
    released = reduce_ledger(locked, (entry("FUNDING_RESERVE_RELEASE", "-20", "release"),))
    assert released.wallet_balance == Decimal("10000")
    assert released.locked_funding_reserve == Decimal("0")


def test_duplicate_ledger_entry_is_rejected() -> None:
    from pa_agent.research_backtest.simulation.ledger import LedgerReplayError, reduce_ledger

    first = reduce_ledger(state(), (entry("ENTRY_FEE", "-10"),))
    with pytest.raises(LedgerReplayError):
        reduce_ledger(first, (entry("ENTRY_FEE", "-10"),))


def test_negative_available_is_invalid_not_clamped() -> None:
    from pa_agent.research_backtest.simulation.ledger import AccountInvariantError, reduce_ledger

    with pytest.raises(AccountInvariantError, match="available"):
        reduce_ledger(state(), (entry("MARGIN_LOCK", "10001"),))


def test_release_beyond_lock_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.ledger import AccountInvariantError, reduce_ledger

    with pytest.raises(AccountInvariantError, match="lock"):
        reduce_ledger(state(), (entry("MARGIN_RELEASE", "-1"),))


def test_mark_equity_uses_wallet_plus_unrealized() -> None:
    from pa_agent.research_backtest.simulation.ledger import mark_equity

    result = mark_equity(state(), Decimal("-250"))
    assert result.equity == Decimal("9750")
    assert result.peak_equity == Decimal("10000")


@given(st.integers(min_value=0, max_value=9000))
def test_margin_lock_release_conserves_wallet(amount: int) -> None:
    from pa_agent.research_backtest.simulation.ledger import reduce_ledger

    locked = reduce_ledger(state(), (entry("MARGIN_LOCK", str(amount), "lock"),))
    released = reduce_ledger(locked, (entry("MARGIN_RELEASE", str(-amount), "release"),))
    assert released.wallet_balance == state().wallet_balance
    assert released.locked_initial_margin == Decimal("0")


def test_only_ledger_reducer_changes_economic_state() -> None:
    from pa_agent.research_backtest.simulation.ledger import validate_account_state

    tampered = replace(state(), equity=Decimal("9999"))
    with pytest.raises(ValueError, match="equity"):
        validate_account_state(tampered)
