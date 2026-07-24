from __future__ import annotations

from decimal import Decimal


def nearest_rank_threshold(
    strengths: tuple[Decimal, ...],
    *,
    quantile_numerator: int,
    quantile_denominator: int,
) -> Decimal:
    if not strengths:
        raise ValueError("threshold input must be nonempty")
    if (
        type(quantile_numerator) is not int
        or type(quantile_denominator) is not int
        or quantile_denominator <= 0
        or not 0 < quantile_numerator <= quantile_denominator
    ):
        raise ValueError("quantile must be a rational value in (0,1]")
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value < 0 for value in strengths
    ):
        raise ValueError("strengths must be finite nonnegative Decimal values")

    ordered = tuple(sorted(strengths))
    rank = (quantile_numerator * len(ordered) + quantile_denominator - 1) // quantile_denominator
    return ordered[rank - 1]
