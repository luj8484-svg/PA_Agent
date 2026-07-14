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
    def __init__(
        self,
        reason: str,
        message: str,
        *,
        expected_values: tuple[tuple[str, str], ...] = (),
        observed_values: tuple[tuple[str, str], ...] = (),
        gap_intervals: tuple[tuple[int, int], ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.expected_values = expected_values
        self.observed_values = observed_values
        self.gap_intervals = gap_intervals


@dataclass(frozen=True, slots=True)
class PreRollSelection:
    daily: tuple[Kline, ...]
    four_hour: tuple[Kline, ...]


@dataclass(frozen=True, slots=True)
class ActiveSegment:
    bars: tuple[Kline, ...]
    gap_at_decision: bool
    gap_intervals: tuple[tuple[int, int], ...]
    gap_observed_step_ms: int | None


def _ordered(bars: Iterable[Kline]) -> tuple[Kline, ...]:
    return tuple(sorted(bars, key=lambda bar: bar.open_time_utc_ms))


def _ensure_unique(bars: tuple[Kline, ...], *, interval_name: str) -> None:
    keys = [bar.open_time_utc_ms for bar in bars]
    if len(keys) != len(set(keys)):
        raise PreRollSelectionError(
            "DATA_SEGMENT_NOT_CONTINUOUS",
            "duplicate bar open time",
            expected_values=((f"unique_{interval_name}_open_times", str(len(keys))),),
            observed_values=((f"unique_{interval_name}_open_times", str(len(set(keys)))),),
        )


def _ensure_continuous(
    bars: tuple[Kline, ...],
    interval_ms: int,
    *,
    interval_name: str,
) -> None:
    if any(not bar.is_closed for bar in bars):
        closed_count = sum(bar.is_closed for bar in bars)
        raise PreRollSelectionError(
            "UNCLOSED_BAR",
            "pre-roll contains an unclosed bar",
            expected_values=((f"closed_{interval_name}_bars", str(len(bars))),),
            observed_values=((f"closed_{interval_name}_bars", str(closed_count)),),
        )
    differences = tuple(
        current.open_time_utc_ms - previous.open_time_utc_ms for previous, current in pairwise(bars)
    )
    if any(difference != interval_ms for difference in differences):
        gaps = tuple(
            (previous.open_time_utc_ms + interval_ms, current.open_time_utc_ms - 1)
            for previous, current in pairwise(bars)
            if current.open_time_utc_ms - previous.open_time_utc_ms > interval_ms
        )
        raise PreRollSelectionError(
            "DATA_SEGMENT_NOT_CONTINUOUS",
            "pre-roll contains a time gap",
            expected_values=((f"{interval_name}_step_ms", str(interval_ms)),),
            observed_values=(
                (f"{interval_name}_steps_ms", ",".join(str(value) for value in differences)),
            ),
            gap_intervals=gaps,
        )


def _select(
    bars: Iterable[Kline],
    *,
    training_start_utc_ms: int,
    required: int,
    interval_ms: int,
    interval_name: str,
) -> tuple[Kline, ...]:
    visible = _ordered(bar for bar in bars if bar.close_time_utc_ms < training_start_utc_ms)
    if len(visible) < required:
        raise PreRollSelectionError(
            "PRE_ROLL_INSUFFICIENT",
            f"requires exactly {required} bars before training start",
            expected_values=((f"pre_roll_{interval_name}_bars", str(required)),),
            observed_values=((f"pre_roll_{interval_name}_bars", str(len(visible))),),
        )
    selected = visible[-required:]
    _ensure_unique(selected, interval_name=interval_name)
    _ensure_continuous(selected, interval_ms, interval_name=interval_name)
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
        interval_name="1d",
    )
    four_hour = _select(
        four_hour_bars,
        training_start_utc_ms=training_start_utc_ms,
        required=FOUR_HOUR_PRE_ROLL,
        interval_ms=FOUR_HOUR_INTERVAL_MS,
        interval_name="4h",
    )
    return PreRollSelection(daily=daily, four_hour=four_hour)


def active_segment(
    bars: Iterable[Kline],
    *,
    interval_ms: int,
    decision_time_utc_ms: int,
) -> ActiveSegment:
    visible = _ordered(bar for bar in bars if bar.close_time_utc_ms <= decision_time_utc_ms)
    if not visible:
        return ActiveSegment(
            bars=(),
            gap_at_decision=False,
            gap_intervals=(),
            gap_observed_step_ms=None,
        )

    segment_start = 0
    gap_intervals: tuple[tuple[int, int], ...] = ()
    gap_observed_step_ms: int | None = None
    for index in range(len(visible) - 1, 0, -1):
        difference = visible[index].open_time_utc_ms - visible[index - 1].open_time_utc_ms
        if difference == interval_ms:
            continue
        if difference == 0:
            raise PreRollSelectionError(
                "DATA_SEGMENT_NOT_CONTINUOUS",
                "active segment contains a duplicate bar open time",
                expected_values=(("unique_active_open_times", str(len(visible))),),
                observed_values=(
                    (
                        "unique_active_open_times",
                        str(len({bar.open_time_utc_ms for bar in visible})),
                    ),
                ),
            )
        segment_start = index
        gap_observed_step_ms = difference
        if difference > interval_ms:
            gap_intervals = (
                (
                    visible[index - 1].open_time_utc_ms + interval_ms,
                    visible[index].open_time_utc_ms - 1,
                ),
            )
        break
    segment = visible[segment_start:]
    gap_at_decision = segment_start > 0 and segment[0].close_time_utc_ms == decision_time_utc_ms
    return ActiveSegment(
        bars=segment,
        gap_at_decision=gap_at_decision,
        gap_intervals=gap_intervals,
        gap_observed_step_ms=gap_observed_step_ms,
    )
