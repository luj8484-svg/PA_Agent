from dataclasses import replace
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from pa_agent.research_backtest.domain.enums import MarketView, TrendState
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market


@given(
    st.decimals(min_value="1", max_value="100000", places=4),
    st.decimals(min_value="0.0001", max_value="1000", places=4),
)
def test_bull_breakout_boundary_is_strict(channel_high, offset):
    channel_low = channel_high - Decimal("1")
    equal = classify_market(
        trend_state=TrendState.BULL,
        current_close=channel_high,
        donchian_high=channel_high,
        donchian_low=channel_low,
    )
    above = classify_market(
        trend_state=TrendState.BULL,
        current_close=channel_high + offset,
        donchian_high=channel_high,
        donchian_low=channel_low,
    )

    assert equal.market_view is MarketView.NO_SETUP
    assert above.market_view is MarketView.LONG


def test_replacing_unrelated_local_object_does_not_mutate_decision():
    decision = classify_market(
        trend_state=TrendState.NEUTRAL,
        current_close=Decimal("100"),
        donchian_high=Decimal("90"),
        donchian_low=Decimal("80"),
    )

    assert replace(decision) == decision
