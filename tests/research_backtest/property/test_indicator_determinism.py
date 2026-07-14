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


def _reference_wilder_atr(highs, lows, closes, period):
    converted = [
        (float(str(high)), float(str(low)), float(str(close)))
        for high, low, close in zip(highs, lows, closes, strict=True)
    ]
    true_ranges = []
    for index, (high, low, _close) in enumerate(converted):
        if index == 0:
            true_ranges.append(high - low)
        else:
            previous_close = converted[index - 1][2]
            true_ranges.append(
                max(high - low, abs(high - previous_close), abs(low - previous_close))
            )
    result = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return tuple(result)
    state = sum(true_ranges[:period]) / float(period)
    result[period - 1] = state
    for index in range(period, len(true_ranges)):
        state = (float(period - 1) * state + true_ranges[index]) / float(period)
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


@given(
    st.lists(
        st.tuples(
            st.decimals(min_value="10", max_value="1000000", places=4),
            st.decimals(min_value="0.0001", max_value="5", places=4),
            st.decimals(min_value="0.0001", max_value="5", places=4),
        ),
        min_size=1,
        max_size=60,
    ),
    st.integers(min_value=1, max_value=20),
)
def test_atr_matches_independent_reference_at_zero_ulp(rows, period):
    closes = [row[0] for row in rows]
    highs = [close + row[1] for close, row in zip(closes, rows, strict=True)]
    lows = [close - row[2] for close, row in zip(closes, rows, strict=True)]

    actual = wilder_atr(highs, lows, closes, period)
    expected = _reference_wilder_atr(highs, lows, closes, period)

    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected, strict=True):
        if expected_value is None:
            assert actual_value is None
        else:
            assert actual_value is not None
            assert actual_value.hex() == expected_value.hex()
