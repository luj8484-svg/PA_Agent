from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_2d.data import (
    CanonicalDataError,
    aggregate_trade_klines,
    build_actionable_candidate_stream,
    build_candidate_stream,
    fast_decision_visible_input_hash,
    funding_record,
    iter_canonical_records,
    kline_from_record,
    minute_bar_from_record,
)
from tests.research_backtest.helpers import INTERVAL_MS, make_bars


def _trade_record(timestamp: int, *, closed: bool = True, close: str = "101") -> dict:
    return {
        "schema_version": "BINANCE_KLINE_V1_EXACT_12",
        "source": "binance_data_vision",
        "stream": "trade",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time_utc_ms": timestamp,
        "close_time_utc_ms": timestamp + 59_999,
        "open": "100.000000000000001",
        "high": "102",
        "low": "99",
        "close": close,
        "base_volume": "2.5",
        "quote_volume": "251.25",
        "trade_count": 3,
        "taker_buy_base_volume": "1.25",
        "taker_buy_quote_volume": "125.625",
        "is_closed": closed,
    }


def _write_month(root: Path, month: str, rows: list[dict]) -> None:
    path = root / "data" / "canonical" / "BTCUSDT" / "trade_1m" / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_iter_records_uses_month_order_range_and_no_duplicates(tmp_path: Path) -> None:
    _write_month(tmp_path, "2020-02", [_trade_record(120_000)])
    _write_month(tmp_path, "2020-01", [_trade_record(0), _trade_record(60_000)])

    values = list(iter_canonical_records(tmp_path, "BTCUSDT", "trade_1m", 60_000, 120_000))

    assert [item["open_time_utc_ms"] for item in values] == [60_000, 120_000]

    _write_month(tmp_path, "2020-02", [_trade_record(60_000)])
    with pytest.raises(CanonicalDataError, match="strictly increasing"):
        list(iter_canonical_records(tmp_path, "BTCUSDT", "trade_1m", 0, 120_000))


def test_kline_and_minute_bar_preserve_decimal_and_require_closed() -> None:
    record = _trade_record(0)

    kline = kline_from_record(record)
    minute = minute_bar_from_record(record)

    assert kline.open == Decimal("100.000000000000001")
    assert minute.open == Decimal("100.000000000000001")
    assert minute.content_hash

    with pytest.raises(CanonicalDataError, match="UNCLOSED_BAR"):
        kline_from_record(_trade_record(0, closed=False))


def test_aggregate_trade_klines_uses_exact_utc_bucket_and_sums_fields() -> None:
    rows = [_trade_record(index * 60_000, close=str(101 + index)) for index in range(240)]
    bars = aggregate_trade_klines(rows, interval="4h")

    assert len(bars) == 1
    bar = bars[0]
    assert bar.open_time_utc_ms == 0
    assert bar.close_time_utc_ms == 14_399_999
    assert bar.open == Decimal("100.000000000000001")
    assert bar.close == Decimal("340")
    assert bar.high == Decimal("102")
    assert bar.low == Decimal("99")
    assert bar.base_volume == Decimal("600.0")
    assert bar.trade_count == 720
    assert bar.interval == "4h"


def test_aggregate_rejects_partial_bucket() -> None:
    rows = [_trade_record(index * 60_000) for index in range(239)]
    with pytest.raises(CanonicalDataError, match="partial 4h bucket"):
        aggregate_trade_klines(rows, interval="4h")


def test_funding_record_uses_real_rate_mark_and_explicit_stress() -> None:
    record = funding_record(
        {
            "symbol": "BTCUSDT",
            "funding_time_utc_ms": 28_800_000,
            "funding_rate": "-0.00012359",
        },
        mark_price=Decimal("12345.67"),
        multiplier=Decimal("2"),
    )

    assert record.symbol == "BTCUSDT"
    assert record.funding_time_utc_ms == 28_800_000
    assert record.funding_rate == Decimal("-0.00024718")
    assert record.mark_price == Decimal("12345.67")
    assert record.record_id.startswith("funding_")


def test_funding_millisecond_jitter_is_bound_to_its_utc_minute() -> None:
    record = funding_record(
        {
            "symbol": "BTCUSDT",
            "funding_time_utc_ms": 28_800_003,
            "funding_rate": "0.0001",
        },
        mark_price=Decimal("100"),
        multiplier=Decimal("1"),
    )

    assert record.funding_time_utc_ms == 28_800_000


def test_candidate_stream_calls_frozen_2a_only_on_closed_four_hour_decisions() -> None:
    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=252)
    four_hour = make_bars(
        interval="4h",
        count=106,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    first_decision = four_hour[-2].close_time_utc_ms
    last_decision = four_hour[-1].close_time_utc_ms

    stream = build_candidate_stream(
        symbol="BTCUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_start_utc_ms=first_decision,
        decision_end_utc_ms=last_decision,
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )

    assert [item.decision_time_utc_ms for item in stream.candidates] == [
        first_decision,
        last_decision,
    ]
    assert not stream.failures


def test_fast_actionable_stream_matches_frozen_candidate_exactly() -> None:
    from dataclasses import replace

    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=251)
    four_hour = make_bars(
        interval="4h",
        count=106,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    previous_close = four_hour[-2].close
    four_hour[-1] = replace(
        four_hour[-1],
        open=previous_close + Decimal("4"),
        high=previous_close + Decimal("7"),
        low=previous_close + Decimal("3"),
        close=previous_close + Decimal("6"),
    )
    decision_time = four_hour[-1].close_time_utc_ms
    reference = build_candidate_stream(
        symbol="BTCUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_start_utc_ms=decision_time,
        decision_end_utc_ms=decision_time,
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )

    fast = build_actionable_candidate_stream(
        symbol="BTCUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_start_utc_ms=decision_time,
        decision_end_utc_ms=decision_time,
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )

    assert fast.candidates == reference.candidates
    assert fast.market_view_counts == {"LONG": 1, "SHORT": 0, "NO_SETUP": 0}
    assert len(fast.trend_evidence) == 1
    assert fast.trend_evidence[0].decision_time_utc_ms == decision_time
    assert fast.trend_evidence[0].is_closed is True


def test_fast_visible_hash_matches_frozen_reference() -> None:
    from pa_agent.research_backtest.domain.validation import VisibleValidationState
    from pa_agent.research_backtest.strategy.visible_input import decision_visible_input_hash

    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=251)
    four_hour = make_bars(
        interval="4h",
        count=106,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    decision_time = four_hour[-1].close_time_utc_ms
    state = VisibleValidationState()

    assert fast_decision_visible_input_hash(
        symbol="BTCUSDT",
        decision_time_utc_ms=decision_time,
        training_start_utc_ms=training_start,
        daily_bars=daily,
        four_hour_bars=four_hour,
        validation_state=state,
    ) == decision_visible_input_hash(
        symbol="BTCUSDT",
        decision_time_utc_ms=decision_time,
        training_start_utc_ms=training_start,
        daily_bars=daily,
        four_hour_bars=four_hour,
        validation_state=state,
    )
