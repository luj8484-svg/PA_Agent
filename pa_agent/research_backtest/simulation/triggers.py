from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.simulation.inputs import MinuteBar
from pa_agent.research_backtest.simulation.positions import IsolatedPosition


class TriggerKind(StrEnum):
    LIQUIDATION = "LIQUIDATION"
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"


@dataclass(frozen=True, slots=True)
class TriggerCandidate:
    kind: TriggerKind
    trigger_price: Decimal
    reference_price: Decimal
    open_price: Decimal
    source: str
    is_gap: bool
    minute_end_equity: Decimal


_TRIGGER_PRIORITY = {
    TriggerKind.LIQUIDATION: 0,
    TriggerKind.STOP: 1,
    TriggerKind.TAKE_PROFIT: 2,
}


def _candidate(
    kind: TriggerKind,
    trigger: Decimal,
    reference: Decimal,
    open_price: Decimal,
    source: str,
    is_gap: bool,
) -> TriggerCandidate:
    return TriggerCandidate(
        kind,
        trigger,
        reference,
        open_price,
        source,
        is_gap,
        Decimal("0"),
    )


def discover_open_gap_candidates(
    position: IsolatedPosition,
    trade_bar: MinuteBar,
    mark_bar: MinuteBar,
    liquidation_price: Decimal,
) -> tuple[TriggerCandidate, ...]:
    found: list[TriggerCandidate] = []
    if position.side is Side.LONG:
        if mark_bar.open <= liquidation_price:
            found.append(
                _candidate(
                    TriggerKind.LIQUIDATION,
                    liquidation_price,
                    mark_bar.open,
                    mark_bar.open,
                    "MARK_1M",
                    True,
                )
            )
        if trade_bar.open <= position.stop_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.STOP,
                    position.stop_trigger_price,
                    trade_bar.open,
                    trade_bar.open,
                    "TRADE_1M",
                    True,
                )
            )
        if trade_bar.open >= position.take_profit_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.TAKE_PROFIT,
                    position.take_profit_trigger_price,
                    trade_bar.open,
                    trade_bar.open,
                    "TRADE_1M",
                    True,
                )
            )
    else:
        if mark_bar.open >= liquidation_price:
            found.append(
                _candidate(
                    TriggerKind.LIQUIDATION,
                    liquidation_price,
                    mark_bar.open,
                    mark_bar.open,
                    "MARK_1M",
                    True,
                )
            )
        if trade_bar.open >= position.stop_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.STOP,
                    position.stop_trigger_price,
                    trade_bar.open,
                    trade_bar.open,
                    "TRADE_1M",
                    True,
                )
            )
        if trade_bar.open <= position.take_profit_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.TAKE_PROFIT,
                    position.take_profit_trigger_price,
                    trade_bar.open,
                    trade_bar.open,
                    "TRADE_1M",
                    True,
                )
            )
    return tuple(sorted(found, key=lambda item: _TRIGGER_PRIORITY[item.kind]))


def choose_open_gap_trigger(candidates: tuple[TriggerCandidate, ...]) -> TriggerCandidate:
    if not candidates:
        raise ValueError("open gap trigger candidates are empty")
    return min(candidates, key=lambda item: _TRIGGER_PRIORITY[item.kind])


def discover_intraminute_candidates(
    position: IsolatedPosition,
    trade_bar: MinuteBar,
    mark_bar: MinuteBar,
    liquidation_price: Decimal,
) -> tuple[TriggerCandidate, ...]:
    found: list[TriggerCandidate] = []
    if position.side is Side.LONG:
        if mark_bar.low <= liquidation_price:
            found.append(
                _candidate(
                    TriggerKind.LIQUIDATION,
                    liquidation_price,
                    liquidation_price,
                    mark_bar.open,
                    "MARK_1M",
                    False,
                )
            )
        if trade_bar.low <= position.stop_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.STOP,
                    position.stop_trigger_price,
                    position.stop_trigger_price,
                    trade_bar.open,
                    "TRADE_1M",
                    False,
                )
            )
        if trade_bar.high >= position.take_profit_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.TAKE_PROFIT,
                    position.take_profit_trigger_price,
                    position.take_profit_trigger_price,
                    trade_bar.open,
                    "TRADE_1M",
                    False,
                )
            )
    else:
        if mark_bar.high >= liquidation_price:
            found.append(
                _candidate(
                    TriggerKind.LIQUIDATION,
                    liquidation_price,
                    liquidation_price,
                    mark_bar.open,
                    "MARK_1M",
                    False,
                )
            )
        if trade_bar.high >= position.stop_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.STOP,
                    position.stop_trigger_price,
                    position.stop_trigger_price,
                    trade_bar.open,
                    "TRADE_1M",
                    False,
                )
            )
        if trade_bar.low <= position.take_profit_trigger_price:
            found.append(
                _candidate(
                    TriggerKind.TAKE_PROFIT,
                    position.take_profit_trigger_price,
                    position.take_profit_trigger_price,
                    trade_bar.open,
                    "TRADE_1M",
                    False,
                )
            )
    return tuple(sorted(found, key=lambda item: _TRIGGER_PRIORITY[item.kind]))


def protective_fill_price(
    side: Side,
    candidate: TriggerCandidate,
    slippage_rate: Decimal,
    tick_size: Decimal,
) -> Decimal:
    if not (Decimal("0") <= slippage_rate < Decimal("1")):
        raise ValueError("slippage rate must be in [0,1)")
    if tick_size <= 0:
        raise ValueError("tick size must be positive")
    if side is Side.LONG:
        raw = candidate.reference_price * (1 - slippage_rate)
        units = (raw / tick_size).to_integral_value(rounding=ROUND_FLOOR)
    else:
        raw = candidate.reference_price * (1 + slippage_rate)
        units = (raw / tick_size).to_integral_value(rounding=ROUND_CEILING)
    return units * tick_size
