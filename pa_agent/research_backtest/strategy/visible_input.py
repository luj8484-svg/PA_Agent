from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.validation import VisibleValidationState
from pa_agent.research_backtest.versions import (
    ATR_VERSION,
    DECISION_VISIBLE_INPUT_VERSION,
    DONCHIAN_VERSION,
    EMA_VERSION,
    INDICATOR_CONFIG_VERSION,
    NUMERIC_BOUNDARY_VERSION,
    PRE_ROLL_POLICY_VERSION,
)
from pa_agent.research_data.models import Kline


def _visible(bars: Iterable[Kline], decision_time_utc_ms: int) -> list[Kline]:
    return sorted(
        (bar for bar in bars if bar.close_time_utc_ms <= decision_time_utc_ms),
        key=lambda bar: bar.open_time_utc_ms,
    )


def decision_visible_input_hash(
    *,
    symbol: str,
    decision_time_utc_ms: int,
    training_start_utc_ms: int,
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    validation_state: VisibleValidationState,
) -> str:
    payload = {
        "decision_time_utc_ms": decision_time_utc_ms,
        "decision_visible_input_version": DECISION_VISIBLE_INPUT_VERSION,
        "daily_bars": _visible(daily_bars, decision_time_utc_ms),
        "four_hour_bars": _visible(four_hour_bars, decision_time_utc_ms),
        "indicator_versions": {
            "atr": ATR_VERSION,
            "config": INDICATOR_CONFIG_VERSION,
            "donchian": DONCHIAN_VERSION,
            "ema": EMA_VERSION,
            "numeric_boundary": NUMERIC_BOUNDARY_VERSION,
        },
        "pre_roll_policy_version": PRE_ROLL_POLICY_VERSION,
        "symbol": symbol,
        "training_start_utc_ms": training_start_utc_ms,
        "visible_validation_state": asdict(validation_state),
    }
    return canonical_sha256(payload)
