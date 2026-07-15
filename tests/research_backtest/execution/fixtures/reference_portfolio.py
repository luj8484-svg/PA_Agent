from __future__ import annotations

from decimal import Decimal


def reference_scale(
    *,
    remaining_risk: Decimal,
    deployable_cash: Decimal,
    risks: tuple[Decimal, ...],
    cash: tuple[Decimal, ...],
) -> Decimal:
    risk_sum = sum(risks, Decimal("0"))
    cash_sum = sum(cash, Decimal("0"))
    risk_scale = Decimal("1") if risk_sum == 0 else remaining_risk / risk_sum
    cash_scale = Decimal("1") if cash_sum == 0 else deployable_cash / cash_sum
    return min(Decimal("1"), risk_scale, cash_scale)
