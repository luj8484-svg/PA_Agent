from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.ema import ema


def _reference_ema(values, period):
    alpha = float(2 / (period + 1))
    state = float(values[0])
    result = [None] * len(values)
    if period == 1:
        result[0] = state
    for index in range(1, len(values)):
        state = alpha * float(values[index]) + (1.0 - alpha) * state
        if index + 1 >= period:
            result[index] = state
    return tuple(result)


@given(
    st.lists(
        st.decimals(min_value="0.0001", max_value="1000000", places=4),
        min_size=1,
        max_size=60,
    ),
    st.integers(min_value=1, max_value=20),
)
def test_ema_matches_independent_fixed_order_reference(values, period):
    assert ema(values, period) == _reference_ema(values, period)


@given(
    st.lists(
        st.decimals(min_value="1", max_value="1000000", places=3),
        min_size=1,
        max_size=40,
    )
)
def test_atr_is_byte_stable_for_repeated_runs(closes):
    highs = [value + Decimal("1") for value in closes]
    lows = [value - Decimal("0.5") for value in closes]

    assert wilder_atr(highs, lows, closes, period=14) == wilder_atr(highs, lows, closes, period=14)
