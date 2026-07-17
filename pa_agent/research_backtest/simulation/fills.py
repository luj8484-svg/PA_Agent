from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.domain.base import formal_identity
from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
from pa_agent.research_backtest.simulation.domain import EngineState
from pa_agent.research_backtest.simulation.ledger import LedgerEntry, LedgerKind, reduce_ledger
from pa_agent.research_backtest.simulation.positions import IsolatedPosition


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


def apply_exit_fill(
    state: EngineState, position: IsolatedPosition, fill: FillEvent
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
        unrealized_pnl=Decimal("0"),
        equity=reduced.wallet_balance,
        peak_equity=max(reduced.peak_equity, reduced.wallet_balance),
    )
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


def stable_entry_plan_order(plans: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(sorted(plans, key=lambda plan: (plan.symbol, plan.plan_id)))
