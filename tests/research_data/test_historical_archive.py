from __future__ import annotations

from datetime import UTC, datetime
from http.client import RemoteDisconnected

import pytest

from pa_agent.research_data.historical_archive import (
    ArchiveObject,
    build_experiment_split_candidate,
    canonicalize_csv_rows,
    estimate_resources,
    fields_equal,
    month_range,
    parse_checksum,
    parse_s3_listing,
    validate_archive_url,
)
from scripts.backfill_binance_historical import (
    aggregate_trade_records,
    merge_record_sequences,
    retry_transient,
)


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1_000)


def test_archive_url_allows_only_official_monthly_binance_objects() -> None:
    value = (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2020-01.zip"
    )
    assert validate_archive_url(value) == value
    with pytest.raises(ValueError, match="OFFICIAL_ARCHIVE_ONLY"):
        validate_archive_url(value.replace("data.binance.vision", "mirror.example"))
    with pytest.raises(ValueError, match="MONTHLY_ARCHIVE_ONLY"):
        validate_archive_url(value.replace("/monthly/", "/daily/"))


def test_parse_s3_listing_preserves_size_etag_and_time() -> None:
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>
      <IsTruncated>false</IsTruncated>
      <Contents><Key>data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip</Key>
      <LastModified>2020-02-01T01:02:03.000Z</LastModified><ETag>&quot;abc&quot;</ETag><Size>123</Size></Contents>
    </ListBucketResult>"""
    objects, next_marker = parse_s3_listing(xml)
    assert objects == (
        ArchiveObject(
            key="data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip",
            size_bytes=123,
            etag="abc",
            last_modified="2020-02-01T01:02:03.000Z",
        ),
    )
    assert next_marker is None


def test_month_range_uses_complete_utc_calendar_months() -> None:
    assert month_range("2023-12", "2024-03") == (
        "2023-12",
        "2024-01",
        "2024-02",
        "2024-03",
    )


def test_experiment_split_has_250_day_preroll_then_36_12_18_months() -> None:
    split = build_experiment_split_candidate(
        common_start_utc_ms=ms("2020-01-01T00:00:00"),
        latest_complete_month="2026-06",
    )
    assert split["version"] == "EXPERIMENT_SPLIT_CANDIDATE_V1"
    assert split["pre_roll"] == {
        "start_utc": "2020-01-01T00:00:00Z",
        "end_utc": "2020-09-06T23:59:59.999000Z",
        "complete_1d_bars": 250,
    }
    assert split["training"] == {
        "start_utc": "2020-10-01T00:00:00Z",
        "end_utc": "2023-09-30T23:59:59.999000Z",
        "complete_utc_months": 36,
    }
    assert split["validation"]["start_utc"] == "2023-10-01T00:00:00Z"
    assert split["validation"]["end_utc"] == "2024-09-30T23:59:59.999000Z"
    assert split["oos"]["start_utc"] == "2024-10-01T00:00:00Z"
    assert split["oos"]["end_utc"] == "2026-03-31T23:59:59.999000Z"
    assert split["coverage_sufficient"] is True


def test_experiment_split_fails_when_complete_months_do_not_fit() -> None:
    split = build_experiment_split_candidate(
        common_start_utc_ms=ms("2022-01-01T00:00:00"),
        latest_complete_month="2026-06",
    )
    assert split["coverage_sufficient"] is False
    assert split["failure"] == "DATA_COVERAGE_INSUFFICIENT"


def test_resource_gate_requires_one_point_five_times_estimated_final_bytes() -> None:
    objects = (
        ArchiveObject("a.zip", 100, "a", "2020-01-01T00:00:00Z"),
        ArchiveObject("b.zip", 300, "b", "2020-01-01T00:00:00Z"),
    )
    estimate = estimate_resources(objects, free_bytes=10_000_000)
    assert estimate["compressed_bytes"] == 400
    assert estimate["safety_multiplier"] == "1.5"
    assert estimate["capacity_status"] == "SUFFICIENT"
    assert estimate["estimated_final_bytes"] > 400
    blocked = estimate_resources(objects, free_bytes=estimate["required_free_bytes"] - 1)
    assert blocked["capacity_status"] == "DISK_CAPACITY_INSUFFICIENT"


def test_decimal_field_comparison_ignores_only_text_scale() -> None:
    assert fields_equal("open", "1.20", "1.20000000")
    assert fields_equal("trade_count", 10, "10")
    assert not fields_equal("close", "1.20", "1.21")


def test_checksum_parser_requires_sha256_and_exact_filename() -> None:
    digest = "a" * 64
    assert parse_checksum(f"{digest}  BTCUSDT-1m-2020-01.zip\n", "BTCUSDT-1m-2020-01.zip") == digest
    with pytest.raises(ValueError, match="CHECKSUM_FILENAME_MISMATCH"):
        parse_checksum(f"{digest}  other.zip\n", "BTCUSDT-1m-2020-01.zip")


def test_archive_trade_rows_are_canonicalized_and_validated() -> None:
    rows = [
        [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote",
            "count",
            "tb_base",
            "tb_quote",
            "ignore",
        ],
        [
            "1577836800000",
            "10.0",
            "11",
            "9",
            "10.5",
            "2",
            "1577836859999",
            "20.5",
            "3",
            "1",
            "10",
            "0",
        ],
    ]
    records = canonicalize_csv_rows(rows, symbol="BTCUSDT", stream="trade", interval="1m")
    assert len(records) == 1
    assert records[0]["open_time_utc_ms"] == 1577836800000
    assert records[0]["close"] == "10.5"
    with pytest.raises(ValueError, match="Invalid OHLC"):
        canonicalize_csv_rows(
            [
                [
                    "1577836800000",
                    "10",
                    "9",
                    "8",
                    "10",
                    "1",
                    "1577836859999",
                    "10",
                    "1",
                    "1",
                    "1",
                    "0",
                ]
            ],
            symbol="BTCUSDT",
            stream="trade",
            interval="1m",
        )


def test_archive_funding_rows_preserve_schedule_and_exact_rate() -> None:
    rows = [
        ["calc_time", "funding_interval_hours", "last_funding_rate"],
        ["1577836800000", "8", "-0.00012359"],
    ]
    records = canonicalize_csv_rows(rows, symbol="BTCUSDT", stream="funding", interval=None)
    assert records == (
        {
            "funding_interval_hours": 8,
            "funding_rate": "-0.00012359",
            "funding_time_utc_ms": 1577836800000,
            "schema_version": "BINANCE_ARCHIVE_FUNDING_V1",
            "source": "binance_data_vision",
            "symbol": "BTCUSDT",
        },
    )


def test_archive_transport_retries_remote_disconnect_then_succeeds() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RemoteDisconnected("temporary close")
        return "ok"

    assert retry_transient(operation, max_attempts=3, sleep=lambda _: None) == "ok"
    assert attempts == 3


def test_gap_fill_records_merge_in_timestamp_order_without_overwrite() -> None:
    archive = (
        {"open_time_utc_ms": 0, "close": "1"},
        {"open_time_utc_ms": 120_000, "close": "3"},
    )
    patch = ({"open_time_utc_ms": 60_000, "close": "2"},)

    merged = merge_record_sequences(archive, patch, key="open_time_utc_ms")

    assert [item["open_time_utc_ms"] for item in merged] == [0, 60_000, 120_000]
    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE"):
        merge_record_sequences(
            archive,
            ({"open_time_utc_ms": 0, "close": "9"},),
            key="open_time_utc_ms",
        )


def test_streaming_trade_aggregation_preserves_ohlcv_and_count() -> None:
    records = (
        {
            "open_time_utc_ms": 0,
            "open": "10",
            "high": "12",
            "low": "9",
            "close": "11",
            "base_volume": "1",
            "quote_volume": "10",
            "trade_count": 2,
            "taker_buy_base_volume": "0.5",
            "taker_buy_quote_volume": "5",
        },
        {
            "open_time_utc_ms": 60_000,
            "open": "11",
            "high": "13",
            "low": "10",
            "close": "12",
            "base_volume": "2",
            "quote_volume": "22",
            "trade_count": 3,
            "taker_buy_base_volume": "1",
            "taker_buy_quote_volume": "11",
        },
    )

    result = aggregate_trade_records(records, interval_ms=120_000)

    assert result[0] == {
        "open_time_utc_ms": 0,
        "close_time_utc_ms": 119_999,
        "open": "10",
        "high": "13",
        "low": "9",
        "close": "12",
        "base_volume": "3",
        "quote_volume": "32",
        "trade_count": 5,
        "taker_buy_base_volume": "1.5",
        "taker_buy_quote_volume": "16",
        "source_1m_count": 2,
    }
