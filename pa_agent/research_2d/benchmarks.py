from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.indicators.ema import ema


def benchmark_metrics(
    daily_by_symbol: dict[str, tuple[object, ...]],
    *,
    split_start_utc_ms: int,
    split_end_utc_ms: int,
) -> dict[str, object]:
    buy_hold: dict[str, Decimal] = {}
    trend: dict[str, Decimal] = {}
    for symbol, all_bars in sorted(daily_by_symbol.items()):
        closes = [bar.close for bar in all_bars]
        ema200 = ema(closes, 200)
        indices = [
            index
            for index, bar in enumerate(all_bars)
            if split_start_utc_ms <= bar.open_time_utc_ms <= split_end_utc_ms
        ]
        if not indices:
            raise ValueError(f"benchmark daily coverage unavailable for {symbol}")
        first, last = indices[0], indices[-1]
        buy_hold[symbol] = all_bars[last].close / all_bars[first].open - 1
        wealth = Decimal("1")
        for index in indices:
            if index == 0 or ema200[index - 1] is None:
                continue
            if all_bars[index - 1].close > Decimal(str(ema200[index - 1])):
                wealth *= all_bars[index].close / all_bars[index].open
        trend[symbol] = wealth - 1
    return {
        "equal_weight_btc_eth_buy_and_hold_return": str(sum(buy_hold.values()) / 2),
        "equal_weight_200d_trend_return": str(sum(trend.values()) / 2),
        "buy_and_hold_by_symbol": {key: str(value) for key, value in buy_hold.items()},
        "trend_200d_by_symbol": {key: str(value) for key, value in trend.items()},
        "benchmark_policy": "UTC_DAILY_OPEN_CLOSE_EQUAL_WEIGHT_V1",
    }
