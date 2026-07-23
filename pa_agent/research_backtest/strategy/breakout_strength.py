from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.enums import MarketView


def calculate_breakout_strength(
    *,
    market_view: MarketView,
    decision_close: Decimal,
    prior_20_bar_donchian_upper: Decimal,
    prior_20_bar_donchian_lower: Decimal,
    decision_atr_4h: Decimal,
) -> Decimal:
    values = {
        "decision_close": decision_close,
        "prior_20_bar_donchian_upper": prior_20_bar_donchian_upper,
        "prior_20_bar_donchian_lower": prior_20_bar_donchian_lower,
        "decision_atr_4h": decision_atr_4h,
    }
    for name, value in values.items():
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal")
        if not value.is_finite():
            raise ValueError(f"{name} must be finite")
    if decision_atr_4h <= 0:
        raise ValueError("decision_atr_4h must be positive")

    if market_view is MarketView.LONG:
        distance = decision_close - prior_20_bar_donchian_upper
    elif market_view is MarketView.SHORT:
        distance = prior_20_bar_donchian_lower - decision_close
    else:
        raise ValueError("market_view must be LONG or SHORT")
    return max(Decimal("0"), distance) / decision_atr_4h
