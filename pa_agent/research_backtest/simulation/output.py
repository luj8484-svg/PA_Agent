from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.simulation.domain import PathState
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent


@dataclass(frozen=True, slots=True)
class PathResult:
    path_state: PathState
    final_processed_time_utc_ms: int
    invalid_reason: str | None = None
    halt_trigger_time_utc_ms: int | None = None
    halt_reason: str | None = None
    entry_disabled: bool = False
    flat_after_halt_time_utc_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SimulationProjection:
    events: tuple[object, ...]
    ledger_entries: tuple[object, ...]
    trades: tuple[object, ...]
    equity_points: tuple[object, ...]
    path_result: PathResult


def terminal_invalid_projection(event: PathInvalidEvent) -> SimulationProjection:
    result = PathResult(
        path_state=PathState.INVALID,
        final_processed_time_utc_ms=event.event_time_utc_ms,
        invalid_reason=event.reason,
    )
    return SimulationProjection((event,), (), (), (), result)
