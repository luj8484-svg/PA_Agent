from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.costs import CostModelSnapshot


def entry_fee(quantity: Decimal, entry_fill: Decimal, cost: CostModelSnapshot) -> Decimal:
    return quantity * entry_fill * cost.effective_fee_rate


def exit_fee_reserve(
    quantity: Decimal,
    planned_exit_notional_price_basis: Decimal,
    cost: CostModelSnapshot,
) -> Decimal:
    return quantity * planned_exit_notional_price_basis * cost.effective_fee_rate
