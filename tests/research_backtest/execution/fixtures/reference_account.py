from __future__ import annotations

from decimal import Decimal


def reference_account_aggregates(
    *,
    wallet_balance: Decimal,
    locked_initial_margin: Decimal,
    locked_fee_reserve: Decimal,
    locked_funding_reserve: Decimal,
    valuation_pnls: tuple[Decimal, ...],
    open_risks: tuple[Decimal, ...],
    pending_risks: tuple[Decimal, ...],
    pending_reserves: tuple[Decimal, ...],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Independent arithmetic reference with no production imports."""
    unrealized = sum(valuation_pnls, Decimal("0"))
    equity = wallet_balance + unrealized
    available = wallet_balance - locked_initial_margin - locked_fee_reserve - locked_funding_reserve
    return (
        equity,
        available,
        sum(open_risks, Decimal("0")),
        sum(pending_risks, Decimal("0")),
        sum(pending_reserves, Decimal("0")),
    )
