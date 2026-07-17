from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.enums import Side


@dataclass(frozen=True, slots=True)
class IsolatedPosition:
    position_id: str
    symbol: str
    side: Side
    quantity: Decimal
    entry_time_utc_ms: int
    entry_price: Decimal
    initial_margin: Decimal
    isolated_margin_balance: Decimal
    stop_trigger_price: Decimal
    take_profit_trigger_price: Decimal
    remaining_fee_reserve: Decimal
    remaining_funding_reserve: Decimal
    planned_funding_slice: Decimal
    remaining_funding_events: int
    origin_plan_id: str
    origin_candidate_id: str
    maximum_exit_time_utc_ms: int
    entry_fee_paid: Decimal = Decimal("0")
    funding_wallet_delta_sum: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.position_id or not self.origin_plan_id or not self.origin_candidate_id:
            raise ValueError("position identity fields must be nonempty")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.side, Side):
            raise ValueError("invalid position market identity")
        positive = (
            "quantity",
            "entry_price",
            "initial_margin",
            "isolated_margin_balance",
            "stop_trigger_price",
            "take_profit_trigger_price",
        )
        nonnegative = (
            "remaining_fee_reserve",
            "remaining_funding_reserve",
            "planned_funding_slice",
            "entry_fee_paid",
        )
        for name in positive + nonnegative:
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be finite Decimal")
            if name in positive and value <= 0:
                raise ValueError(f"{name} must be positive")
            if name in nonnegative and value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.isolated_margin_balance != self.initial_margin:
            raise ValueError("fixed isolated margin must equal origin initial margin")
        if type(self.remaining_funding_events) is not int or self.remaining_funding_events < 0:
            raise ValueError("remaining funding event count must be nonnegative integer")


def position_from_entry_plan(plan: object) -> IsolatedPosition:
    funding_count = plan.funding_event_upper_bound
    funding_reserve = plan.funding_reserve
    planned_slice = funding_reserve / Decimal(funding_count) if funding_count > 0 else Decimal("0")
    return IsolatedPosition(
        position_id=f"position:{plan.plan_id}",
        symbol=plan.symbol,
        side=plan.side,
        quantity=plan.quantity,
        entry_time_utc_ms=plan.target_execution_time_utc_ms,
        entry_price=plan.expected_entry_fill_price,
        initial_margin=plan.initial_margin,
        isolated_margin_balance=plan.initial_margin,
        stop_trigger_price=plan.stop_trigger_price,
        take_profit_trigger_price=plan.take_profit_trigger_price,
        remaining_fee_reserve=plan.exit_fee_reserve,
        remaining_funding_reserve=funding_reserve,
        planned_funding_slice=planned_slice,
        remaining_funding_events=funding_count,
        origin_plan_id=plan.plan_id,
        origin_candidate_id=plan.candidate_id,
        maximum_exit_time_utc_ms=plan.maximum_exit_time_utc_ms,
        entry_fee_paid=plan.entry_fee,
    )
