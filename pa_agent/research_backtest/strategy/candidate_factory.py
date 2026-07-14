from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from pa_agent.research_backtest.domain.candidates import (
    StrategyCandidate,
    strategy_candidate,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import TrendState, ValidationReason
from pa_agent.research_backtest.domain.failures import ValidationFailure, validation_failure
from pa_agent.research_backtest.domain.validation import (
    VisibleValidationState,
    highest_priority_failure,
)
from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.donchian import previous_donchian
from pa_agent.research_backtest.indicators.ema import ema
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
from pa_agent.research_backtest.strategy.pre_roll import (
    DAILY_INTERVAL_MS,
    FOUR_HOUR_INTERVAL_MS,
    PreRollSelectionError,
    active_segment,
    select_exact_pre_roll,
)
from pa_agent.research_backtest.strategy.visible_input import decision_visible_input_hash
from pa_agent.research_backtest.versions import (
    ATR_VERSION,
    DONCHIAN_VERSION,
    EMA_VERSION,
    INDICATOR_CONFIG_VERSION,
    LOCKED_PYTHON_IMPLEMENTATION,
    LOCKED_PYTHON_VERSION,
    NUMERIC_BOUNDARY_VERSION,
    PRE_ROLL_POLICY_VERSION,
    STRATEGY_VERSION,
    assert_runtime_lock,
)
from pa_agent.research_data.models import Kline

INDICATOR_CONFIG_HASH = canonical_sha256(
    {
        "atr_period_4h": 14,
        "atr_version": ATR_VERSION,
        "donchian_lookback_4h": 20,
        "donchian_version": DONCHIAN_VERSION,
        "ema_periods_daily": (50, 200),
        "ema_version": EMA_VERSION,
        "indicator_config_version": INDICATOR_CONFIG_VERSION,
        "numeric_boundary_version": NUMERIC_BOUNDARY_VERSION,
        "pre_roll_policy_version": PRE_ROLL_POLICY_VERSION,
        "python_implementation": LOCKED_PYTHON_IMPLEMENTATION,
        "python_version": LOCKED_PYTHON_VERSION,
    }
)
STRATEGY_CONFIG_HASH = canonical_sha256(
    {
        "donchian_comparison": "STRICT",
        "strategy_version": STRATEGY_VERSION,
        "trend_filter": "DAILY_EMA50_EMA200",
    }
)


def _failure(
    *,
    reason: str | ValidationReason,
    symbol: str,
    decision_time_utc_ms: int,
    affected_interval: str,
    code_commit: str,
    dependency_lock_hash: str,
    expected: tuple[tuple[str, str], ...] = (),
    observed: tuple[tuple[str, str], ...] = (),
) -> ValidationFailure:
    return validation_failure(
        reason=reason,
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        affected_interval=affected_interval,
        decision_visible_input_hash=None,
        expected_values=expected,
        observed_values=observed,
        gap_intervals=(),
        indicator_config_hash=INDICATOR_CONFIG_HASH,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )


def _materialize(bars: Iterable[Kline]) -> tuple[Kline, ...]:
    return tuple(sorted(bars, key=lambda bar: bar.open_time_utc_ms))


def _trend_state(daily_close: Decimal, ema50: Decimal, ema200: Decimal) -> TrendState:
    if daily_close > ema200 and ema50 > ema200:
        return TrendState.BULL
    if daily_close < ema200 and ema50 < ema200:
        return TrendState.BEAR
    return TrendState.NEUTRAL


def build_candidate(
    *,
    symbol: str,
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    training_start_utc_ms: int,
    decision_time_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
    validation_state: VisibleValidationState | None = None,
) -> StrategyCandidate | ValidationFailure:
    assert_runtime_lock()
    if validation_state is None:
        validation_state = VisibleValidationState()
    daily = _materialize(daily_bars)
    four_hour = _materialize(four_hour_bars)

    try:
        pre_roll = select_exact_pre_roll(
            daily,
            four_hour,
            training_start_utc_ms=training_start_utc_ms,
        )
    except PreRollSelectionError as error:
        return _failure(
            reason=error.reason,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    visible_daily = pre_roll.daily + tuple(
        bar
        for bar in daily
        if training_start_utc_ms <= bar.open_time_utc_ms
        and bar.close_time_utc_ms <= decision_time_utc_ms
    )
    visible_four_hour = pre_roll.four_hour + tuple(
        bar
        for bar in four_hour
        if training_start_utc_ms <= bar.open_time_utc_ms
        and bar.close_time_utc_ms <= decision_time_utc_ms
    )
    identity_invalid = (
        any(
            bar.symbol != symbol or bar.interval != "1d" or bar.stream != "trade"
            for bar in visible_daily
        )
        or any(
            bar.symbol != symbol or bar.interval != "4h" or bar.stream != "trade"
            for bar in visible_four_hour
        )
    )
    if identity_invalid:
        return _failure(
            reason=ValidationReason.INDICATOR_BOUNDARY_INVALID,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    if any(not bar.is_closed for bar in (*visible_daily, *visible_four_hour)) or not (
        validation_state.daily_closed and validation_state.four_hour_closed
    ):
        return _failure(
            reason=ValidationReason.UNCLOSED_BAR,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    if not (validation_state.daily_native_valid and validation_state.four_hour_native_valid):
        return _failure(
            reason=ValidationReason.NATIVE_AGGREGATION_NOT_VALID,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    current_bars = [
        bar for bar in visible_four_hour if bar.close_time_utc_ms == decision_time_utc_ms
    ]
    if len(current_bars) != 1:
        return _failure(
            reason=ValidationReason.INDICATOR_BOUNDARY_INVALID,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
            expected=(("decision_bar_count", "1"),),
            observed=(("decision_bar_count", str(len(current_bars))),),
        )

    try:
        daily_segment = active_segment(
            visible_daily,
            interval_ms=DAILY_INTERVAL_MS,
            decision_time_utc_ms=decision_time_utc_ms,
        )
        four_hour_segment = active_segment(
            visible_four_hour,
            interval_ms=FOUR_HOUR_INTERVAL_MS,
            decision_time_utc_ms=decision_time_utc_ms,
        )
    except PreRollSelectionError as error:
        return _failure(
            reason=error.reason,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    reasons: set[str] = set()
    if not (validation_state.daily_continuous and validation_state.four_hour_continuous):
        reasons.add(ValidationReason.DATA_SEGMENT_NOT_CONTINUOUS.value)
    if daily_segment.gap_at_decision or four_hour_segment.gap_at_decision:
        reasons.add(ValidationReason.DATA_SEGMENT_NOT_CONTINUOUS.value)
    if len(daily_segment.bars) < 200 or len(four_hour_segment.bars) < 21:
        reasons.add(ValidationReason.INDICATOR_WARMING_UP.value)
    priority_reason = highest_priority_failure(reasons)
    if priority_reason is not None:
        return _failure(
            reason=priority_reason,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    if not daily_segment.bars:
        return _failure(
            reason=ValidationReason.DAILY_BAR_NOT_AVAILABLE,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    daily_closes = [bar.close for bar in daily_segment.bars]
    four_highs = [bar.high for bar in four_hour_segment.bars]
    four_lows = [bar.low for bar in four_hour_segment.bars]
    four_closes = [bar.close for bar in four_hour_segment.bars]
    try:
        ema50_value = ema(daily_closes, 50)[-1]
        ema200_value = ema(daily_closes, 200)[-1]
        atr14_value = wilder_atr(four_highs, four_lows, four_closes, 14)[-1]
        if ema50_value is None or ema200_value is None or atr14_value is None:
            return _failure(
                reason=ValidationReason.INDICATOR_WARMING_UP,
                symbol=symbol,
                decision_time_utc_ms=decision_time_utc_ms,
                affected_interval="1d/4h",
                code_commit=code_commit,
                dependency_lock_hash=dependency_lock_hash,
            )
        ema50_decimal = float64_to_decimal_15sig(ema50_value)
        ema200_decimal = float64_to_decimal_15sig(ema200_value)
        atr14_decimal = float64_to_decimal_15sig(atr14_value)
        donchian_high, donchian_low = previous_donchian(
            four_highs,
            four_lows,
            index=len(four_hour_segment.bars) - 1,
            lookback=20,
        )
    except ValueError:
        return _failure(
            reason=ValidationReason.INDICATOR_NON_FINITE_OR_NON_POSITIVE,
            symbol=symbol,
            decision_time_utc_ms=decision_time_utc_ms,
            affected_interval="1d/4h",
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    daily_close = daily_segment.bars[-1].close
    trend_state = _trend_state(daily_close, ema50_decimal, ema200_decimal)
    current_bar = current_bars[0]
    market = classify_market(
        trend_state=trend_state,
        current_close=current_bar.close,
        donchian_high=donchian_high,
        donchian_low=donchian_low,
    )
    visible_hash = decision_visible_input_hash(
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        training_start_utc_ms=training_start_utc_ms,
        daily_bars=daily_segment.bars,
        four_hour_bars=four_hour_segment.bars,
        validation_state=validation_state,
    )
    return strategy_candidate(
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        decision_bar_open_time_utc_ms=current_bar.open_time_utc_ms,
        market_view=market.market_view,
        market_reason=market.market_reason,
        decision_close=current_bar.close,
        daily_close=daily_close,
        trend_state=trend_state,
        ema50_daily=ema50_decimal,
        ema200_daily=ema200_decimal,
        atr14_4h=atr14_decimal,
        donchian_high_previous_20=donchian_high,
        donchian_low_previous_20=donchian_low,
        decision_visible_input_hash=visible_hash,
        indicator_config_hash=INDICATOR_CONFIG_HASH,
        strategy_config_hash=STRATEGY_CONFIG_HASH,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
