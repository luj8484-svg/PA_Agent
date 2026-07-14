from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

FAILURE_PRIORITY = (
    "PRE_ROLL_INSUFFICIENT",
    "DATA_SEGMENT_NOT_CONTINUOUS",
    "INDICATOR_WARMING_UP",
)


@dataclass(frozen=True, slots=True)
class VisibleValidationState:
    daily_native_valid: bool = True
    four_hour_native_valid: bool = True
    daily_closed: bool = True
    four_hour_closed: bool = True
    daily_continuous: bool = True
    four_hour_continuous: bool = True


def highest_priority_failure(reasons: Iterable[str]) -> str | None:
    reason_set = frozenset(reasons)
    for reason in FAILURE_PRIORITY:
        if reason in reason_set:
            return reason
    return min(reason_set) if reason_set else None
