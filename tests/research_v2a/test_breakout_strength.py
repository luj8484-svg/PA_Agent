from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.canonical import canonical_decimal
from pa_agent.research_backtest.domain.enums import MarketView
from pa_agent.research_backtest.strategy.breakout_strength import (
    calculate_breakout_strength,
)


def test_long_breakout_strength_uses_frozen_decimal_formula() -> None:
    result = calculate_breakout_strength(
        market_view=MarketView.LONG,
        decision_close=Decimal("105"),
        prior_20_bar_donchian_upper=Decimal("101"),
        prior_20_bar_donchian_lower=Decimal("90"),
        decision_atr_4h=Decimal("2"),
    )

    assert result == Decimal("2")
    assert canonical_decimal(result) == "2"


def test_short_breakout_strength_uses_frozen_decimal_formula() -> None:
    result = calculate_breakout_strength(
        market_view=MarketView.SHORT,
        decision_close=Decimal("94"),
        prior_20_bar_donchian_upper=Decimal("110"),
        prior_20_bar_donchian_lower=Decimal("99"),
        decision_atr_4h=Decimal("2"),
    )

    assert result == Decimal("2.5")
    assert canonical_decimal(result) == "2.5"


@pytest.mark.parametrize(
    ("market_view", "decision_close", "upper", "lower"),
    [
        (MarketView.LONG, "99", "101", "90"),
        (MarketView.SHORT, "101", "110", "99"),
    ],
)
def test_non_breakout_distance_is_clamped_to_zero(
    market_view: MarketView,
    decision_close: str,
    upper: str,
    lower: str,
) -> None:
    assert calculate_breakout_strength(
        market_view=market_view,
        decision_close=Decimal(decision_close),
        prior_20_bar_donchian_upper=Decimal(upper),
        prior_20_bar_donchian_lower=Decimal(lower),
        decision_atr_4h=Decimal("3"),
    ) == Decimal("0")


@pytest.mark.parametrize("atr", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_non_positive_or_non_finite_atr_fails_closed(atr: Decimal) -> None:
    with pytest.raises(ValueError, match="decision_atr_4h"):
        calculate_breakout_strength(
            market_view=MarketView.LONG,
            decision_close=Decimal("105"),
            prior_20_bar_donchian_upper=Decimal("101"),
            prior_20_bar_donchian_lower=Decimal("90"),
            decision_atr_4h=atr,
        )


def test_non_actionable_market_view_fails_closed() -> None:
    with pytest.raises(ValueError, match="LONG or SHORT"):
        calculate_breakout_strength(
            market_view=MarketView.NO_SETUP,
            decision_close=Decimal("100"),
            prior_20_bar_donchian_upper=Decimal("101"),
            prior_20_bar_donchian_lower=Decimal("90"),
            decision_atr_4h=Decimal("2"),
        )


def test_binary_float_inputs_are_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        calculate_breakout_strength(
            market_view=MarketView.LONG,
            decision_close=105.0,  # type: ignore[arg-type]
            prior_20_bar_donchian_upper=Decimal("101"),
            prior_20_bar_donchian_lower=Decimal("90"),
            decision_atr_4h=Decimal("2"),
        )
