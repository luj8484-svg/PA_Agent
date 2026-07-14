from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState


@dataclass(frozen=True, slots=True)
class MarketDecision:
    market_view: MarketView
    market_reason: MarketReason


def classify_market(
    *,
    trend_state: TrendState,
    current_close: Decimal,
    donchian_high: Decimal,
    donchian_low: Decimal,
) -> MarketDecision:
    if any(not value.is_finite() for value in (current_close, donchian_high, donchian_low)):
        raise ValueError("market rule inputs must be finite")
    if donchian_high < donchian_low:
        raise ValueError("Donchian high must be >= Donchian low")

    if trend_state is TrendState.NEUTRAL:
        return MarketDecision(MarketView.NO_SETUP, MarketReason.TREND_NEUTRAL)
    if trend_state is TrendState.BULL:
        if current_close > donchian_high:
            return MarketDecision(MarketView.LONG, MarketReason.BULL_DONCHIAN_BREAKOUT)
        if current_close < donchian_low:
            return MarketDecision(MarketView.NO_SETUP, MarketReason.BREAKOUT_AGAINST_TREND)
        return MarketDecision(MarketView.NO_SETUP, MarketReason.NO_BREAKOUT)
    if current_close < donchian_low:
        return MarketDecision(MarketView.SHORT, MarketReason.BEAR_DONCHIAN_BREAKOUT)
    if current_close > donchian_high:
        return MarketDecision(MarketView.NO_SETUP, MarketReason.BREAKOUT_AGAINST_TREND)
    return MarketDecision(MarketView.NO_SETUP, MarketReason.NO_BREAKOUT)

