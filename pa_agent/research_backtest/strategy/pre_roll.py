from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from pa_agent.research_data.models import Kline

DAILY_PRE_ROLL = 250
FOUR_HOUR_PRE_ROLL = 100
DAILY_INTERVAL_MS = 86_400_000
FOUR_HOUR_INTERVAL_MS = 14_400_000


class PreRollSelectionError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PreRollSelection:
    daily: tuple[Kline, ...]
    four_hour: tuple[Kline, ...]


@dataclass(frozen=True, slots=True)
class ActiveSegment:
    bars: tuple[Kline, ...]
    gap_at_decision: bool


def _ordered_unique(bars: Iterable[Kline]) -> tuple[Kline, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: bar.open_time_utc_ms))
    keys = [bar.open_time_utc_ms for bar in ordered]
    if len(keys) != len(set(keys)):
        raise PreRollSelectionError("DATA_SEGMENT_NOT_CONTINUOUS", "duplicate bar open time")
    return ordered


def _ensure_continuous(bars: tuple[Kline, ...], interval_ms: int) -> None:
    if any(not bar.is_closed for bar in bars):
        raise PreRollSelectionError("UNCLOSED_BAR", "pre-roll contains an unclosed bar")
    if any(
        current.open_time_utc_ms - previous.open_time_utc_ms != interval_ms
        for previous, current in pairwise(bars)
    ):
        raise PreRollSelectionError("DATA_SEGMENT_NOT_CONTINUOUS", "pre-roll contains a time gap")


def _select(
    bars: Iterable[Kline],
    *,
    training_start_utc_ms: int,
    required: int,
    interval_ms: int,
) -> tuple[Kline, ...]:
    visible = _ordered_unique(bar for bar in bars if bar.close_time_utc_ms < training_start_utc_ms)
    if len(visible) < required:
        raise PreRollSelectionError(
            "PRE_ROLL_INSUFFICIENT",
            f"requires exactly {required} bars before training start",
        )
    selected = visible[-required:]
    _ensure_continuous(selected, interval_ms)
    return selected


def select_exact_pre_roll(
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    *,
    training_start_utc_ms: int,
) -> PreRollSelection:
    daily = _select(
        daily_bars,
        training_start_utc_ms=training_start_utc_ms,
        required=DAILY_PRE_ROLL,
        interval_ms=DAILY_INTERVAL_MS,
    )
    four_hour = _select(
        four_hour_bars,
        training_start_utc_ms=training_start_utc_ms,
        required=FOUR_HOUR_PRE_ROLL,
        interval_ms=FOUR_HOUR_INTERVAL_MS,
    )
    return PreRollSelection(daily=daily, four_hour=four_hour)


def active_segment(
    bars: Iterable[Kline],
    *,
    interval_ms: int,
    decision_time_utc_ms: int,
) -> ActiveSegment:
    visible = _ordered_unique(bar for bar in bars if bar.close_time_utc_ms <= decision_time_utc_ms)
    if not visible:
        return ActiveSegment(bars=(), gap_at_decision=False)

    segment_start = 0
    for index in range(1, len(visible)):
        if visible[index].open_time_utc_ms - visible[index - 1].open_time_utc_ms != interval_ms:
            segment_start = index
    segment = visible[segment_start:]
    gap_at_decision = segment_start > 0 and segment[0].close_time_utc_ms == decision_time_utc_ms
    return ActiveSegment(bars=segment, gap_at_decision=gap_at_decision)
