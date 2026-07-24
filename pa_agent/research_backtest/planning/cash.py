from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

CANONICAL_REQUIRED_CASH_CONTEXT_VERSION = "CANONICAL_REQUIRED_CASH_DECIMAL_CONTEXT_V1"
CANONICAL_REQUIRED_CASH_QUANTIZATION_VERSION = "EXCHANGE_QUANTIZED_INPUTS_NO_POST_ROUNDING_V1"
_CANONICAL_REQUIRED_CASH_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def calculate_final_required_cash(
    *,
    quantity: Decimal,
    expected_entry_fill_price: Decimal,
    planned_exit_notional_price_basis: Decimal,
    effective_fee_rate: Decimal,
    effective_adverse_rate_cap: Decimal,
    funding_event_upper_bound: int,
) -> Decimal:
    """Return the frozen 1x cash reserve using one deterministic Decimal path.

    Final callers supply the already step-quantized quantity and already tick-quantized
    price inputs. CASH-F23 uses the same function with raw quantity for its explicitly
    unscaled denominator. No currency rounding is applied after the four exact frozen
    components; Canonical serialization removes representational trailing zeroes only.
    """
    decimal_values = (
        quantity,
        expected_entry_fill_price,
        planned_exit_notional_price_basis,
        effective_fee_rate,
        effective_adverse_rate_cap,
    )
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in decimal_values):
        raise ValueError("required cash inputs must be finite Decimal values")
    if (
        quantity < 0
        or expected_entry_fill_price <= 0
        or planned_exit_notional_price_basis <= 0
        or effective_fee_rate < 0
        or effective_adverse_rate_cap < 0
    ):
        raise ValueError("required cash inputs violate their frozen domains")
    if type(funding_event_upper_bound) is not int or funding_event_upper_bound < 0:
        raise ValueError("funding event upper bound must be a nonnegative integer")

    with localcontext(_CANONICAL_REQUIRED_CASH_CONTEXT):
        initial_margin = quantity * expected_entry_fill_price
        entry_fee = quantity * expected_entry_fill_price * effective_fee_rate
        exit_fee = quantity * planned_exit_notional_price_basis * effective_fee_rate
        funding = (
            quantity
            * planned_exit_notional_price_basis
            * effective_adverse_rate_cap
            * funding_event_upper_bound
        )
        return ((initial_margin + entry_fee) + exit_fee) + funding
