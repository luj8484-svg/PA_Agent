from __future__ import annotations

from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.intents import EntryIntent
from pa_agent.research_backtest.domain.market_inputs import (
    TargetEventWatermark,
    TargetMinuteOpenSnapshot,
)

FOUR_HOUR_MS = 14_400_000
MINUTE_MS = 60_000


class TargetMinuteUnavailableError(ValueError):
    """A target watermark proves the required open event is missing."""


def next_four_hour_anchor(decision_time_utc_ms: int) -> int:
    if type(decision_time_utc_ms) is not int or decision_time_utc_ms < 0:
        raise ValueError("decision time must be nonnegative integer UTC milliseconds")
    anchor = decision_time_utc_ms + 1
    if anchor % FOUR_HOUR_MS != 0:
        raise ValueError("decision time must be an exact closed 4H close")
    return anchor


def entry_target_time(decision_time_utc_ms: int, config: ExecutionTimeConfig) -> int:
    return next_four_hour_anchor(decision_time_utc_ms) + config.entry_delay_minutes * MINUTE_MS


def require_target_reached(event_time_utc_ms: int, target_time_utc_ms: int) -> None:
    if type(event_time_utc_ms) is not int or type(target_time_utc_ms) is not int:
        raise ValueError("event and target times must be integer UTC milliseconds")
    if event_time_utc_ms < target_time_utc_ms:
        raise ValueError("planning factory called before target time")


def resolve_target_open(
    intent: EntryIntent,
    *,
    snapshot: TargetMinuteOpenSnapshot | None,
    watermark: TargetEventWatermark,
) -> TargetMinuteOpenSnapshot:
    if watermark.symbol != intent.symbol:
        raise ValueError("watermark symbol does not match EntryIntent")
    if watermark.target_open_time_utc_ms != intent.target_execution_time_utc_ms:
        raise ValueError("watermark target does not match EntryIntent")
    require_target_reached(
        watermark.event_watermark_time_utc_ms,
        intent.target_execution_time_utc_ms,
    )
    if snapshot is None:
        raise TargetMinuteUnavailableError("target minute open Snapshot is unavailable")
    if snapshot.symbol != intent.symbol:
        raise ValueError("target open symbol does not match EntryIntent")
    if snapshot.open_time_utc_ms != intent.target_execution_time_utc_ms:
        raise ValueError("target open time does not match EntryIntent")
    return snapshot
