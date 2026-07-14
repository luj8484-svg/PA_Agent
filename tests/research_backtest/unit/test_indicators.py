import json
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.donchian import previous_donchian
from pa_agent.research_backtest.indicators.ema import ema

FIXTURE = Path("tests/research_backtest/fixtures/indicator_golden_v1.json")


def _decimal_list(values):
    return [Decimal(value) for value in values]


def test_indicator_golden_fixture_is_exact():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    ema_case = fixture["ema"]
    ema_result = ema(_decimal_list(ema_case["values"]), ema_case["period"])
    assert [None if value is None else str(value) for value in ema_result] == ema_case["expected"]

    atr_case = fixture["atr"]
    atr_result = wilder_atr(
        _decimal_list(atr_case["highs"]),
        _decimal_list(atr_case["lows"]),
        _decimal_list(atr_case["closes"]),
        atr_case["period"],
    )
    assert [None if value is None else str(value) for value in atr_result] == atr_case["expected"]

    channel = previous_donchian(
        _decimal_list(fixture["donchian"]["highs"]),
        _decimal_list(fixture["donchian"]["lows"]),
        index=fixture["donchian"]["index"],
        lookback=fixture["donchian"]["lookback"],
    )
    assert channel == (
        Decimal(fixture["donchian"]["expected_high"]),
        Decimal(fixture["donchian"]["expected_low"]),
    )


def test_ema_uses_first_value_as_internal_seed_and_min_periods():
    assert ema([Decimal("5"), Decimal("5")], period=3) == (None, None)
    assert ema([Decimal("5"), Decimal("5"), Decimal("5")], period=3) == (
        None,
        None,
        5.0,
    )


def test_atr_rejects_mismatched_or_invalid_ohlc():
    with pytest.raises(ValueError, match="same length"):
        wilder_atr([Decimal("2")], [], [Decimal("1")], period=14)
    with pytest.raises(ValueError, match="high must be >= low"):
        wilder_atr([Decimal("1")], [Decimal("2")], [Decimal("1.5")], period=1)


def test_donchian_excludes_current_bar_and_requires_full_lookback():
    highs = [Decimal(value) for value in (1, 2, 3, 999)]
    lows = [Decimal(value) for value in (0, -1, -2, -999)]

    assert previous_donchian(highs, lows, index=3, lookback=3) == (
        Decimal("3"),
        Decimal("-2"),
    )
    with pytest.raises(ValueError, match="lookback"):
        previous_donchian(highs, lows, index=2, lookback=3)


@pytest.mark.parametrize("period", [0, -1])
def test_indicator_periods_must_be_positive(period):
    with pytest.raises(ValueError, match="positive"):
        ema([Decimal("1")], period=period)
    with pytest.raises(ValueError, match="positive"):
        wilder_atr([Decimal("1")], [Decimal("1")], [Decimal("1")], period=period)
