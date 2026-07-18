from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.domain.base import formal_identity
from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
from pa_agent.research_backtest.simulation.domain import EngineState
from pa_agent.research_backtest.simulation.ledger import (
    AccountInvariantError,
    LedgerEntry,
    LedgerKind,
    LedgerReplayError,
    commit_valuation,
    reduce_ledger,
)
from pa_agent.research_backtest.simulation.positions import (
    IsolatedPosition,
    position_from_entry_plan,
)


class FillAction(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


@dataclass(frozen=True, slots=True)
class FillEvent:
    fill_id: str
    fill_content_hash: str
    plan_id: str
    candidate_id: str
    position_id: str
    symbol: str
    side: Side
    action: FillAction
    event_time_utc_ms: int
    quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    selected_exit_reason: ScheduledExitReason | None
    matched_exit_reasons: tuple[ScheduledExitReason, ...]


@dataclass(frozen=True, slots=True)
class TradeRecord:
    position_id: str
    symbol: str
    side: Side
    entry_time_utc_ms: int
    exit_time_utc_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    funding: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    exit_reason: ScheduledExitReason | str
    origin_plan_id: str
    origin_candidate_id: str


@dataclass(frozen=True, slots=True)
class EntryBatchCommit:
    state: EngineState
    fills: tuple[FillEvent, ...]
    ledger_entries: tuple[LedgerEntry, ...]
    positions: tuple[IsolatedPosition, ...]


@dataclass(frozen=True, slots=True)
class EntryBatchCommitFailure:
    state: EngineState
    reason: str
    error_type: str
    fills: tuple[FillEvent, ...] = ()
    ledger_entries: tuple[LedgerEntry, ...] = ()
    positions: tuple[IsolatedPosition, ...] = ()


@dataclass(frozen=True, slots=True)
class ExitBatchCommit:
    state: EngineState
    fills: tuple[FillEvent, ...]
    ledger_entries: tuple[LedgerEntry, ...]
    trades: tuple[TradeRecord, ...]


@dataclass(frozen=True, slots=True)
class ExitBatchCommitFailure:
    state: EngineState
    reason: str
    error_type: str
    fills: tuple[FillEvent, ...] = ()
    ledger_entries: tuple[LedgerEntry, ...] = ()
    trades: tuple[TradeRecord, ...] = ()


def _fill(payload: dict[str, object]) -> FillEvent:
    fill_id, digest = formal_identity("fill_", payload)
    return FillEvent(fill_id, digest, **payload)


def make_entry_fill(plan: object) -> FillEvent:
    return _fill(
        {
            "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id,
            "position_id": f"position:{plan.plan_id}",
            "symbol": plan.symbol,
            "side": plan.side,
            "action": FillAction.ENTRY,
            "event_time_utc_ms": plan.target_execution_time_utc_ms,
            "quantity": plan.quantity,
            "fill_price": plan.expected_entry_fill_price,
            "fee": plan.entry_fee,
            "selected_exit_reason": None,
            "matched_exit_reasons": (),
        }
    )


def make_scheduled_exit_fill(
    plan: object,
    matched_reasons: tuple[ScheduledExitReason, ...],
    selected_reason: ScheduledExitReason,
) -> FillEvent:
    if selected_reason not in matched_reasons:
        raise ValueError("selected scheduled exit reason was not matched")
    return _fill(
        {
            "plan_id": plan.plan_id,
            "candidate_id": plan.origin_candidate_id,
            "position_id": plan.position_id,
            "symbol": plan.symbol,
            "side": plan.position_side,
            "action": FillAction.EXIT,
            "event_time_utc_ms": plan.target_execution_time_utc_ms,
            "quantity": plan.quantity,
            "fill_price": plan.expected_exit_fill_price,
            "fee": plan.expected_exit_fee,
            "selected_exit_reason": selected_reason,
            "matched_exit_reasons": matched_reasons,
        }
    )


def make_protective_exit_fill(
    position: IsolatedPosition,
    candidate: object,
    event_time_utc_ms: int,
    *,
    slippage_rate: Decimal,
    fee_rate: Decimal,
    tick_size: Decimal,
) -> FillEvent:
    from pa_agent.research_backtest.simulation.triggers import protective_fill_price

    price = protective_fill_price(position.side, candidate, slippage_rate, tick_size)
    fee = position.quantity * price * fee_rate
    trigger_kind = candidate.kind.value
    return _fill(
        {
            "plan_id": f"protective:{position.position_id}:{event_time_utc_ms}:{trigger_kind}",
            "candidate_id": position.origin_candidate_id,
            "position_id": position.position_id,
            "symbol": position.symbol,
            "side": position.side,
            "action": FillAction.EXIT,
            "event_time_utc_ms": event_time_utc_ms,
            "quantity": position.quantity,
            "fill_price": price,
            "fee": fee,
            "selected_exit_reason": None,
            "matched_exit_reasons": (),
        }
    )


def _ledger(
    fill: FillEvent,
    suffix: str,
    kind: LedgerKind,
    *,
    wallet: Decimal = Decimal("0"),
    margin: Decimal = Decimal("0"),
    fee_reserve: Decimal = Decimal("0"),
    funding_reserve: Decimal = Decimal("0"),
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=f"{fill.fill_id}:{suffix}",
        event_time_utc_ms=fill.event_time_utc_ms,
        kind=kind,
        wallet_delta=wallet,
        initial_margin_delta=margin,
        fee_reserve_delta=fee_reserve,
        funding_reserve_delta=funding_reserve,
        pending_plan_reserve_delta=Decimal("0"),
    )


def apply_entry_fill(
    state: EngineState, fill: FillEvent, position: IsolatedPosition
) -> tuple[EngineState, tuple[LedgerEntry, ...]]:
    if fill.action is not FillAction.ENTRY or fill.plan_id != position.origin_plan_id:
        raise ValueError("entry Fill does not match position origin")
    if fill.plan_id in state.consumed_plan_ids:
        raise ValueError("entry plan already consumed")
    if any(item.symbol == position.symbol for item in state.positions):
        raise ValueError("existing position violates one-way symbol constraint")
    entries = (
        _ledger(fill, "entry-fee", LedgerKind.ENTRY_FEE, wallet=-fill.fee),
        _ledger(fill, "margin-lock", LedgerKind.MARGIN_LOCK, margin=position.initial_margin),
        _ledger(
            fill,
            "fee-reserve-lock",
            LedgerKind.FEE_RESERVE_LOCK,
            fee_reserve=position.remaining_fee_reserve,
        ),
        _ledger(
            fill,
            "funding-reserve-lock",
            LedgerKind.FUNDING_RESERVE_LOCK,
            funding_reserve=position.remaining_funding_reserve,
        ),
    )
    reduced = reduce_ledger(state, entries)
    reduced = replace(
        reduced,
        positions=tuple(sorted((*state.positions, position), key=lambda item: item.symbol)),
        consumed_plan_ids=tuple(sorted((*state.consumed_plan_ids, fill.plan_id))),
    )
    return reduced, entries


def apply_entry_batch(
    state: EngineState, plans: tuple[object, ...]
) -> EntryBatchCommit | EntryBatchCommitFailure:
    """Rehearse an immutable entry batch and expose only all-or-none results."""
    try:
        ordered = stable_entry_plan_order(plans)
        if len({plan.plan_id for plan in ordered}) != len(ordered):
            raise ValueError("duplicate entry Plan ID")
        if len({plan.symbol for plan in ordered}) != len(ordered):
            raise ValueError("duplicate entry Plan symbol")
        temporary = state
        fills: list[FillEvent] = []
        entries: list[LedgerEntry] = []
        positions: list[IsolatedPosition] = []
        for plan in ordered:
            fill = make_entry_fill(plan)
            position = position_from_entry_plan(plan)
            temporary, plan_entries = apply_entry_fill(temporary, fill, position)
            fills.append(fill)
            entries.extend(plan_entries)
            positions.append(position)
        return EntryBatchCommit(
            temporary,
            tuple(fills),
            tuple(entries),
            tuple(positions),
        )
    except (AccountInvariantError, LedgerReplayError, ValueError) as exc:
        return EntryBatchCommitFailure(
            state=state,
            reason="ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION",
            error_type=type(exc).__name__,
        )


def apply_exit_fill(
    state: EngineState,
    position: IsolatedPosition,
    fill: FillEvent,
    *,
    remaining_unrealized_pnl: Decimal,
    commit_final_valuation: bool = True,
) -> tuple[EngineState, tuple[LedgerEntry, ...], TradeRecord]:
    if fill.action is not FillAction.EXIT or fill.position_id != position.position_id:
        raise ValueError("exit Fill does not match open position")
    if position.position_id in state.consumed_close_ids:
        raise ValueError("position close already consumed")
    if fill.quantity != position.quantity or fill.symbol != position.symbol:
        raise ValueError("exit Fill geometry does not match position")
    gross = (
        position.quantity * (fill.fill_price - position.entry_price)
        if position.side is Side.LONG
        else position.quantity * (position.entry_price - fill.fill_price)
    )
    entries = (
        _ledger(fill, "exit-fee", LedgerKind.EXIT_FEE, wallet=-fill.fee),
        _ledger(fill, "realized-pnl", LedgerKind.REALIZED_PNL, wallet=gross),
        _ledger(
            fill,
            "margin-release",
            LedgerKind.MARGIN_RELEASE,
            margin=-position.initial_margin,
        ),
        _ledger(
            fill,
            "fee-reserve-release",
            LedgerKind.FEE_RESERVE_RELEASE,
            fee_reserve=-position.remaining_fee_reserve,
        ),
        _ledger(
            fill,
            "funding-reserve-release",
            LedgerKind.FUNDING_RESERVE_RELEASE,
            funding_reserve=-position.remaining_funding_reserve,
        ),
    )
    reduced = reduce_ledger(state, entries)
    reduced = replace(
        reduced,
        positions=tuple(
            item for item in state.positions if item.position_id != position.position_id
        ),
        consumed_plan_ids=tuple(sorted(set((*state.consumed_plan_ids, fill.plan_id)))),
        consumed_close_ids=tuple(sorted((*state.consumed_close_ids, position.position_id))),
    )
    if commit_final_valuation:
        reduced = commit_valuation(reduced, remaining_unrealized_pnl)
    net = gross - position.entry_fee_paid - fill.fee + position.funding_wallet_delta_sum
    trade = TradeRecord(
        position_id=position.position_id,
        symbol=position.symbol,
        side=position.side,
        entry_time_utc_ms=position.entry_time_utc_ms,
        exit_time_utc_ms=fill.event_time_utc_ms,
        entry_price=position.entry_price,
        exit_price=fill.fill_price,
        quantity=position.quantity,
        entry_fee=position.entry_fee_paid,
        exit_fee=fill.fee,
        funding=position.funding_wallet_delta_sum,
        gross_pnl=gross,
        net_pnl=net,
        exit_reason=fill.selected_exit_reason or "PROTECTIVE",
        origin_plan_id=position.origin_plan_id,
        origin_candidate_id=position.origin_candidate_id,
    )
    return reduced, entries, trade


def apply_exit_batch(
    state: EngineState,
    items: tuple[tuple[IsolatedPosition, FillEvent], ...],
    *,
    remaining_unrealized_pnl: Decimal,
) -> ExitBatchCommit | ExitBatchCommitFailure:
    """Rehearse all same-stage exits and expose one valuation commit."""
    try:
        ordered = tuple(
            sorted(items, key=lambda item: (item[0].symbol, item[0].position_id, item[1].fill_id))
        )
        position_ids = tuple(position.position_id for position, _ in ordered)
        fill_ids = tuple(fill.fill_id for _, fill in ordered)
        if len(set(position_ids)) != len(position_ids):
            raise ValueError("duplicate exit position in batch")
        if len(set(fill_ids)) != len(fill_ids):
            raise ValueError("duplicate exit Fill in batch")
        temporary = state
        fills: list[FillEvent] = []
        entries: list[LedgerEntry] = []
        trades: list[TradeRecord] = []
        for position, fill in ordered:
            temporary, item_entries, trade = apply_exit_fill(
                temporary,
                position,
                fill,
                remaining_unrealized_pnl=remaining_unrealized_pnl,
                commit_final_valuation=False,
            )
            fills.append(fill)
            entries.extend(item_entries)
            trades.append(trade)
        temporary = commit_valuation(temporary, remaining_unrealized_pnl)
        return ExitBatchCommit(temporary, tuple(fills), tuple(entries), tuple(trades))
    except (AccountInvariantError, LedgerReplayError, ValueError) as exc:
        return ExitBatchCommitFailure(
            state=state,
            reason="EXIT_BATCH_POST_PLAN_INVARIANT_VIOLATION",
            error_type=type(exc).__name__,
        )


def stable_entry_plan_order(plans: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(sorted(plans, key=lambda plan: (plan.symbol, plan.plan_id)))
