from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.audit_binance_data_readiness import (
    classify_freshness,
    coverage_day_metrics,
    deterministic_sample,
    fields_equal,
    latest_closed_boundaries,
    max_download_timestamp,
    merge_records,
)


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1_000)


def test_latest_closed_boundaries_use_exchange_time_and_exclude_open_bars() -> None:
    boundaries = latest_closed_boundaries(utc_ms("2026-07-19T10:23:45"))

    assert boundaries["1m"] == {
        "open_time_utc_ms": utc_ms("2026-07-19T10:22:00"),
        "close_time_utc_ms": utc_ms("2026-07-19T10:22:59.999"),
    }
    assert boundaries["4h"] == {
        "open_time_utc_ms": utc_ms("2026-07-19T04:00:00"),
        "close_time_utc_ms": utc_ms("2026-07-19T07:59:59.999"),
    }
    assert boundaries["1d"] == {
        "open_time_utc_ms": utc_ms("2026-07-18T00:00:00"),
        "close_time_utc_ms": utc_ms("2026-07-18T23:59:59.999"),
    }


def test_deterministic_sample_is_reproducible_and_timestamp_ordered() -> None:
    records = tuple({"open_time_utc_ms": index * 60_000} for index in range(100))

    first = deterministic_sample(
        records,
        count=10,
        seed=20260719,
        namespace="BTCUSDT|trade_1m",
        timestamp_field="open_time_utc_ms",
    )
    second = deterministic_sample(
        tuple(reversed(records)),
        count=10,
        seed=20260719,
        namespace="BTCUSDT|trade_1m",
        timestamp_field="open_time_utc_ms",
    )

    assert first == second
    assert len(first) == 10
    assert [item["open_time_utc_ms"] for item in first] == sorted(
        item["open_time_utc_ms"] for item in first
    )


def test_merge_records_counts_identical_overlap_and_rejects_conflicts() -> None:
    old = (
        {"open_time_utc_ms": 0, "close": "1"},
        {"open_time_utc_ms": 60_000, "close": "2"},
    )
    new = (
        {"open_time_utc_ms": 60_000, "close": "2"},
        {"open_time_utc_ms": 120_000, "close": "3"},
    )

    merged, duplicate_count = merge_records(old, new, key_field="open_time_utc_ms")

    assert duplicate_count == 1
    assert tuple(item["open_time_utc_ms"] for item in merged) == (0, 60_000, 120_000)
    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE"):
        merge_records(
            old,
            ({"open_time_utc_ms": 60_000, "close": "9"},),
            key_field="open_time_utc_ms",
        )


@pytest.mark.parametrize(
    ("data_lag_minutes", "data_lag_4h_bars", "expected"),
    (
        (0, 0, "FRESH"),
        (239, 0, "FRESH"),
        (240, 1, "STALE"),
        (1_439, 5, "STALE"),
        (1_440, 6, "SEVERELY_STALE"),
    ),
)
def test_freshness_thresholds_are_frozen(
    data_lag_minutes: int, data_lag_4h_bars: int, expected: str
) -> None:
    assert (
        classify_freshness(
            data_lag_minutes=data_lag_minutes,
            data_lag_4h_bars=data_lag_4h_bars,
        )
        == expected
    )


def test_coverage_day_metrics_are_canonical_decimal_strings() -> None:
    metrics = coverage_day_metrics(0, 86_400_000)

    assert metrics == {
        "joint_common_duration_days": "1",
        "required_approximate_days": "2008.833750",
        "sufficient": False,
    }


def test_reconciliation_compares_decimal_values_not_text_scale() -> None:
    assert fields_equal("open", "59999.6", "59999.60000000")
    assert fields_equal("funding_rate", "0.0000948", "0.00009480")
    assert fields_equal("trade_count", 42, 42)
    assert not fields_equal("close", "1.0", "1.0001")
    assert not fields_equal("open_time_utc_ms", 1, 2)


def test_download_timestamp_is_found_in_nested_delta_manifest() -> None:
    manifest = {
        "dataset_manifests": {
            "BTCUSDT_trade_1m": {
                "delta_acquisition": {
                    "completed_at_utc_ms": 200,
                    "pages": [{"downloaded_at_utc_ms": 150}],
                }
            }
        }
    }

    assert max_download_timestamp(manifest) == 200
