from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def reference_prices(
    side: str,
    open_price: Decimal,
    atr: Decimal,
    slippage: Decimal,
    tick: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    if side == "LONG":
        entry = ceil_step(open_price * (Decimal("1") + slippage), tick)
        stop = ceil_step(entry - Decimal("2") * atr, tick)
        take_profit = floor_step(entry + Decimal("3") * atr, tick)
        stop_fill = floor_step(stop * (Decimal("1") - slippage), tick)
        take_profit_fill = floor_step(take_profit * (Decimal("1") - slippage), tick)
    else:
        entry = floor_step(open_price * (Decimal("1") - slippage), tick)
        stop = floor_step(entry + Decimal("2") * atr, tick)
        take_profit = ceil_step(entry - Decimal("3") * atr, tick)
        stop_fill = ceil_step(stop * (Decimal("1") + slippage), tick)
        take_profit_fill = ceil_step(take_profit * (Decimal("1") + slippage), tick)
    return entry, stop, take_profit, stop_fill, take_profit_fill


def reference_sizing(
    *,
    equity: Decimal,
    entry: Decimal,
    stop_fill: Decimal,
    exit_basis: Decimal,
    fee_rate: Decimal,
    funding_rate: Decimal,
    funding_count: int,
    step: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    unit_risk = (
        abs(entry - stop_fill)
        + entry * fee_rate
        + stop_fill * fee_rate
        + exit_basis * funding_rate * funding_count
    )
    budget = equity * Decimal("0.005")
    raw = budget / unit_risk
    quantity = floor_step(raw, step)
    return unit_risk, budget, raw, quantity
