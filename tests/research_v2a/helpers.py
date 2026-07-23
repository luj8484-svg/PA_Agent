from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.candidates import StrategyCandidate, strategy_candidate
from pa_agent.research_backtest.domain.enums import (
    MarketReason,
    MarketView,
    TrendState,
)


def make_candidate(
    *,
    decision_time_utc_ms: int,
    strength: str,
    symbol: str = "BTCUSDT",
    market_view: MarketView = MarketView.LONG,
    suffix: str = "a",
) -> StrategyCandidate:
    atr = Decimal("10")
    distance = Decimal(strength) * atr
    if market_view is MarketView.LONG:
        close = Decimal("100") + distance
        upper = Decimal("100")
        lower = Decimal("80")
        daily_close = Decimal("110")
        ema50 = Decimal("105")
        ema200 = Decimal("100")
        trend_state = TrendState.BULL
        reason = MarketReason.BULL_DONCHIAN_BREAKOUT
    else:
        close = Decimal("100") - distance
        upper = Decimal("120")
        lower = Decimal("100")
        daily_close = Decimal("90")
        ema50 = Decimal("95")
        ema200 = Decimal("100")
        trend_state = TrendState.BEAR
        reason = MarketReason.BEAR_DONCHIAN_BREAKOUT
    return strategy_candidate(
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        decision_bar_open_time_utc_ms=decision_time_utc_ms - 14_400_000,
        market_view=market_view,
        market_reason=reason,
        decision_close=close,
        daily_close=daily_close,
        trend_state=trend_state,
        ema50_daily=ema50,
        ema200_daily=ema200,
        atr14_4h=atr,
        donchian_high_previous_20=upper,
        donchian_low_previous_20=lower,
        decision_visible_input_hash=suffix * 64,
        indicator_config_hash="b" * 64,
        strategy_config_hash="c" * 64,
        code_commit="d" * 40,
        dependency_lock_hash="e" * 64,
    )
