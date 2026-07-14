from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal


def _price(value: Decimal) -> float:
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0.0:
        raise ValueError("OHLC inputs must be finite and positive")
    return converted


def wilder_atr(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    period: int,
) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, and closes must have the same length")
    if not highs:
        return ()

    converted: list[tuple[float, float, float]] = []
    for high_value, low_value, close_value in zip(highs, lows, closes, strict=True):
        high = _price(high_value)
        low = _price(low_value)
        close = _price(close_value)
        if high < low:
            raise ValueError("high must be >= low")
        converted.append((high, low, close))

    true_ranges: list[float] = []
    for index, (high, low, _) in enumerate(converted):
        if index == 0:
            true_range = high - low
        else:
            previous_close = converted[index - 1][2]
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        true_ranges.append(true_range)

    result: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return tuple(result)

    state = sum(true_ranges[:period]) / float(period)
    result[period - 1] = state
    for index in range(period, len(true_ranges)):
        state = (float(period - 1) * state + true_ranges[index]) / float(period)
        result[index] = state
    return tuple(result)

