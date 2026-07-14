from decimal import Decimal

from pa_agent.research_data.models import Kline

INTERVAL_MS = {"4h": 14_400_000, "1d": 86_400_000}


def make_bars(
    *,
    interval: str,
    count: int,
    start_utc_ms: int = 0,
    symbol: str = "BTCUSDT",
) -> list[Kline]:
    step = INTERVAL_MS[interval]
    bars = []
    for index in range(count):
        open_time = start_utc_ms + index * step
        close = Decimal("100") + Decimal(index)
        bars.append(
            Kline(
                source="binance_fapi",
                stream="trade",
                symbol=symbol,
                interval=interval,
                open_time_utc_ms=open_time,
                close_time_utc_ms=open_time + step - 1,
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                base_volume=Decimal("10"),
                quote_volume=Decimal("1000"),
                trade_count=10,
                taker_buy_base_volume=Decimal("4"),
                taker_buy_quote_volume=Decimal("400"),
                is_closed=True,
            )
        )
    return bars
