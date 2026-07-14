from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal


def _positive_finite_float(value: Decimal) -> float:
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0.0:
        raise ValueError("indicator inputs must be finite and positive")
    return converted


def ema(values: Sequence[Decimal], period: int) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return ()

    alpha = float(2 / (period + 1))
    state = _positive_finite_float(values[0])
    result: list[float | None] = [None] * len(values)
    if period == 1:
        result[0] = state

    for index in range(1, len(values)):
        current = _positive_finite_float(values[index])
        state = alpha * current + (1.0 - alpha) * state
        if index + 1 >= period:
            result[index] = state
    return tuple(result)
