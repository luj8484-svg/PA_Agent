from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.simulation.domain import EngineState, PathState


class ExposureDisposition(StrEnum):
    OPEN_EXITED = "OPEN_EXITED"
    INTRAMINUTE_EXITED = "INTRAMINUTE_EXITED"
    HELD_TO_CLOSE = "HELD_TO_CLOSE"


def uses_full_minute_extreme(disposition: ExposureDisposition) -> bool:
    if disposition is ExposureDisposition.OPEN_EXITED:
        return False
    return disposition in {
        ExposureDisposition.INTRAMINUTE_EXITED,
        ExposureDisposition.HELD_TO_CLOSE,
    }


def drawdown_breached(peak_equity: Decimal, observed_equity: Decimal) -> bool:
    if peak_equity <= 0:
        raise ValueError("peak equity must be positive")
    return (peak_equity - observed_equity) / peak_equity >= Decimal("0.10")


def apply_halt(state: EngineState, event_time_utc_ms: int, reason: str) -> EngineState:
    if state.path_state is PathState.INVALID:
        raise ValueError("invalid path cannot transition to halted")
    if state.path_state is PathState.HALTED:
        return state
    return replace(
        state,
        path_state=PathState.HALTED,
        halt_trigger_time_utc_ms=event_time_utc_ms,
        halt_reason=reason,
    )
