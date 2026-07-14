from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext


def float64_to_decimal_15sig(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("float64 value must be finite")
    if value == 0.0:
        return Decimal("0")

    exact = Decimal.from_float(value)
    exponent = exact.copy_abs().adjusted()
    quantum = Decimal(1).scaleb(exponent - 14)
    with localcontext() as context:
        context.prec = max(50, len(exact.as_tuple().digits) + 10)
        result = exact.quantize(quantum, rounding=ROUND_HALF_EVEN)
    if result.is_zero():
        return Decimal("0")
    return result
