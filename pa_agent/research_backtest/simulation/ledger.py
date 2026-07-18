from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.simulation.domain import EngineState


class LedgerReplayError(ValueError):
    pass


class AccountInvariantError(ValueError):
    pass


class LedgerKind(StrEnum):
    ENTRY_FEE = "ENTRY_FEE"
    EXIT_FEE = "EXIT_FEE"
    FUNDING = "FUNDING"
    REALIZED_PNL = "REALIZED_PNL"
    MARGIN_LOCK = "MARGIN_LOCK"
    MARGIN_RELEASE = "MARGIN_RELEASE"
    FEE_RESERVE_LOCK = "FEE_RESERVE_LOCK"
    FEE_RESERVE_RELEASE = "FEE_RESERVE_RELEASE"
    FUNDING_RESERVE_LOCK = "FUNDING_RESERVE_LOCK"
    FUNDING_RESERVE_RELEASE = "FUNDING_RESERVE_RELEASE"
    PENDING_PLAN_RESERVE_LOCK = "PENDING_PLAN_RESERVE_LOCK"
    PENDING_PLAN_RESERVE_RELEASE = "PENDING_PLAN_RESERVE_RELEASE"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    event_time_utc_ms: int
    kind: LedgerKind
    wallet_delta: Decimal
    initial_margin_delta: Decimal
    fee_reserve_delta: Decimal
    funding_reserve_delta: Decimal
    pending_plan_reserve_delta: Decimal

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("ledger entry_id must be nonempty")
        if type(self.event_time_utc_ms) is not int or self.event_time_utc_ms < 0:
            raise ValueError("ledger event time must be nonnegative UTC milliseconds")
        if not isinstance(self.kind, LedgerKind):
            raise ValueError("unsupported ledger kind")
        for name in (
            "wallet_delta",
            "initial_margin_delta",
            "fee_reserve_delta",
            "funding_reserve_delta",
            "pending_plan_reserve_delta",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be finite Decimal")


def available_balance(state: EngineState) -> Decimal:
    return (
        state.wallet_balance
        - state.locked_initial_margin
        - state.locked_fee_reserve
        - state.locked_funding_reserve
        - state.pending_plan_reserve
    )


def _validate_ledger_balances(state: EngineState) -> None:
    locks = (
        state.locked_initial_margin,
        state.locked_fee_reserve,
        state.locked_funding_reserve,
        state.pending_plan_reserve,
    )
    if any(value < 0 for value in locks):
        raise AccountInvariantError("account lock cannot be negative")
    if available_balance(state) < 0:
        raise AccountInvariantError("available balance cannot be negative")


def validate_account_state(state: EngineState) -> None:
    _validate_ledger_balances(state)
    if state.equity != state.wallet_balance + state.unrealized_pnl:
        raise ValueError("equity must equal wallet plus unrealized PnL")
    if state.peak_equity < state.equity:
        raise ValueError("peak equity cannot be below current equity")


def reduce_ledger(previous: EngineState, entries: tuple[LedgerEntry, ...]) -> EngineState:
    seen = set(previous.consumed_ledger_ids)
    state = previous
    for item in entries:
        if item.entry_id in seen:
            raise LedgerReplayError(f"ledger entry already consumed: {item.entry_id}")
        seen.add(item.entry_id)
        wallet = state.wallet_balance + item.wallet_delta
        state = replace(
            state,
            wallet_balance=wallet,
            locked_initial_margin=state.locked_initial_margin + item.initial_margin_delta,
            locked_fee_reserve=state.locked_fee_reserve + item.fee_reserve_delta,
            locked_funding_reserve=(state.locked_funding_reserve + item.funding_reserve_delta),
            pending_plan_reserve=(state.pending_plan_reserve + item.pending_plan_reserve_delta),
            consumed_ledger_ids=tuple(sorted(seen)),
        )
    _validate_ledger_balances(state)
    return state


def mark_equity(state: EngineState, unrealized_pnl: Decimal) -> EngineState:
    if not isinstance(unrealized_pnl, Decimal) or not unrealized_pnl.is_finite():
        raise ValueError("unrealized PnL must be finite Decimal")
    equity = state.wallet_balance + unrealized_pnl
    marked = replace(
        state,
        unrealized_pnl=unrealized_pnl,
        equity=equity,
        peak_equity=max(state.peak_equity, equity),
    )
    validate_account_state(marked)
    return marked
