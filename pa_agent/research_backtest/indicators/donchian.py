from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def previous_donchian(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    *,
    index: int,
    lookback: int,
) -> tuple[Decimal, Decimal]:
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if len(highs) != len(lows):
        raise ValueError("highs and lows must have the same length")
    if index < lookback or index >= len(highs):
        raise ValueError("index must have a full previous lookback and a current bar")

    previous_highs = highs[index - lookback : index]
    previous_lows = lows[index - lookback : index]
    if any(not value.is_finite() for value in (*previous_highs, *previous_lows)):
        raise ValueError("Donchian inputs must be finite")
    return max(previous_highs), min(previous_lows)
