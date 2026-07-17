from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from pa_agent.research_backtest.domain.contracts import ContractRuleCoverage
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.domain.sizing import SizingRejected


class PriceGeometryInvalid(SizingRejected):
    def __init__(self) -> None:
        super().__init__("PRICE_GEOMETRY_INVALID")


def _finite(value: Decimal, name: str, *, positive: bool = True) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    _finite(value, "value", positive=False)
    _finite(step, "step")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    _finite(value, "value", positive=False)
    _finite(tick, "tick")
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


@dataclass(frozen=True, slots=True)
class PriceGeometry:
    expected_entry_fill_price: Decimal
    stop_trigger_price: Decimal
    take_profit_trigger_price: Decimal
    expected_stop_fill_price: Decimal
    expected_take_profit_fill_price: Decimal
    planned_exit_notional_price_basis: Decimal

    def as_price_tuple(self) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        return (
            self.expected_entry_fill_price,
            self.stop_trigger_price,
            self.take_profit_trigger_price,
            self.expected_stop_fill_price,
            self.expected_take_profit_fill_price,
        )


def adverse_gap(
    side: Side,
    decision_close: Decimal,
    target_open: Decimal,
    atr: Decimal,
) -> Decimal:
    for value, name in (
        (decision_close, "decision_close"),
        (target_open, "target_open"),
        (atr, "atr"),
    ):
        _finite(value, name)
    gap = target_open - decision_close if side is Side.LONG else decision_close - target_open
    if gap > Decimal("0.5") * atr:
        raise SizingRejected("GAP_TOO_LARGE")
    return gap


def price_geometry(
    side: Side,
    target_open: Decimal,
    atr: Decimal,
    cost: CostModelSnapshot,
    contract: ContractRuleCoverage,
) -> PriceGeometry:
    _finite(target_open, "target_open")
    _finite(atr, "atr")
    tick = contract.tick_size
    slippage = cost.effective_slippage_rate
    one = Decimal("1")
    if side is Side.LONG:
        entry = ceil_to_tick(target_open * (one + slippage), tick)
        stop = ceil_to_tick(entry - Decimal("2") * atr, tick)
        take_profit = floor_to_step(entry + Decimal("3") * atr, tick)
        stop_fill = floor_to_step(stop * (one - slippage), tick)
        take_profit_fill = floor_to_step(take_profit * (one - slippage), tick)
        valid = stop_fill <= stop < entry < take_profit and take_profit_fill > entry
    elif side is Side.SHORT:
        entry = floor_to_step(target_open * (one - slippage), tick)
        stop = floor_to_step(entry + Decimal("2") * atr, tick)
        take_profit = ceil_to_tick(entry - Decimal("3") * atr, tick)
        stop_fill = ceil_to_tick(stop * (one + slippage), tick)
        take_profit_fill = ceil_to_tick(take_profit * (one + slippage), tick)
        valid = take_profit_fill < entry < stop <= stop_fill
    else:
        raise ValueError("unsupported side")
    prices = (entry, stop, take_profit, stop_fill, take_profit_fill)
    if any(value <= 0 for value in prices) or not valid:
        raise PriceGeometryInvalid()
    return PriceGeometry(
        entry,
        stop,
        take_profit,
        stop_fill,
        take_profit_fill,
        max(entry, stop_fill, take_profit_fill),
    )


def expected_exit_price(
    position_side: Side,
    target_open: Decimal,
    cost: CostModelSnapshot,
    contract: ContractRuleCoverage,
) -> Decimal:
    _finite(target_open, "target_open")
    one = Decimal("1")
    if position_side is Side.LONG:
        return floor_to_step(target_open * (one - cost.effective_slippage_rate), contract.tick_size)
    if position_side is Side.SHORT:
        return ceil_to_tick(target_open * (one + cost.effective_slippage_rate), contract.tick_size)
    raise ValueError("unsupported position side")
