from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.research_data.materiality_audit import (
    AUTHORITY_POLICY_VERSION,
    bar_materiality_record,
    build_pre_roll_identity,
    classify_differences,
    classify_final_status,
    classify_split,
    decimal_difference,
    mark_gap_evidence,
    quantized_stop_tp,
    summarize_candidate_materiality,
)


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def test_decimal_difference_uses_exact_decimal_arithmetic() -> None:
    result = decimal_difference("100", "99")

    assert result == {
        "absolute_difference": "1",
        "relative_difference": "0.01",
    }


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"base_volume", "quote_volume", "trade_count"}, "AUDIT_ONLY_DIFFERENCE"),
        ({"close", "base_volume"}, "PRICE_DIFFERENCE"),
    ],
)
def test_classify_differences_distinguishes_price_fields(fields: set[str], expected: str) -> None:
    assert classify_differences(fields) == expected


def test_bar_materiality_record_contains_hashes_and_exact_field_differences() -> None:
    native = {
        "open_time_utc_ms": utc_ms("2024-01-01T00:00:00Z"),
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "base_volume": "11",
        "quote_volume": "1000",
        "trade_count": 9,
        "taker_buy_base_volume": "5",
        "taker_buy_quote_volume": "500",
    }
    aggregated = {**native, "close": "104", "base_volume": "10"}

    result = bar_materiality_record(
        symbol="BTCUSDT",
        interval="4h",
        native=native,
        aggregated=aggregated,
        differing_field_names={"close", "base_volume"},
    )

    assert result["materiality_category"] == "PRICE_DIFFERENCE"
    assert len(result["native_bar_hash"]) == 64
    assert len(result["aggregated_bar_hash"]) == 64
    assert [item["field"] for item in result["differing_fields"]] == [
        "close",
        "base_volume",
    ]
    assert result["differing_fields"][0]["absolute_difference"] == "1"
    assert result["split"] == "VALIDATION"


def test_bar_materiality_record_respects_frozen_validation_issue_fields() -> None:
    native = {
        "open_time_utc_ms": utc_ms("2024-01-01T00:00:00Z"),
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "base_volume": "11",
        "quote_volume": "1000",
        "trade_count": 9,
        "taker_buy_base_volume": "5",
        "taker_buy_quote_volume": "500",
    }
    aggregated = {**native, "close": "104", "base_volume": "10"}

    result = bar_materiality_record(
        symbol="BTCUSDT",
        interval="4h",
        native=native,
        aggregated=aggregated,
        differing_field_names={"close"},
    )

    assert [item["field"] for item in result["differing_fields"]] == ["close"]


def test_classify_split_uses_frozen_calendar_boundaries() -> None:
    assert classify_split(utc_ms("2023-09-30T23:59:59.999Z")) == "TRAINING"
    assert classify_split(utc_ms("2024-09-30T23:59:59.999Z")) == "VALIDATION"
    assert classify_split(utc_ms("2024-10-01T00:00:00Z")) == "OOS"


def test_mark_gap_evidence_does_not_invent_trade_impact() -> None:
    evidence = mark_gap_evidence(
        symbol="BTCUSDT",
        start_utc="2024-08-12T10:02:00Z",
        end_utc="2024-08-12T10:03:59.999000Z",
    )

    assert evidence["minute_count"] == 2
    assert evidence["split"] == "VALIDATION"
    assert evidence["is_oos"] is False
    assert evidence["affects_candidate_decision"] is False
    assert evidence["open_position_crosses"] is None
    assert evidence["affected_trade_count"] is None
    assert evidence["expected_2c_result"] == "INVALID_IF_ACTIVE_POSITION_OR_ECONOMIC_EVENT"


def test_pre_roll_identity_covers_every_daily_bar_before_training() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    records = [
        {
            "symbol": "BTCUSDT",
            "interval": "1d",
            "open_time_utc_ms": int((start + timedelta(days=index)).timestamp() * 1000),
            "close_time_utc_ms": int((start + timedelta(days=index + 1)).timestamp() * 1000) - 1,
            "close": str(100 + index),
        }
        for index in range(274)
    ]

    result = build_pre_roll_identity(
        records_by_symbol={"BTCUSDT": records, "ETHUSDT": records},
        data_bundle_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )

    assert result["version"] == "EXPERIMENT_SPLIT_CANDIDATE_V2"
    assert result["minimum_required_pre_roll_1d_bars"] == 250
    assert result["actual_pre_roll_1d_bars"] == {"BTCUSDT": 274, "ETHUSDT": 274}
    assert result["actual_pre_roll_end_utc"] == "2020-09-30T23:59:59.999000Z"
    assert len(result["pre_roll_content_hash"]) == 64
    assert result["authority_policy_version"] == AUTHORITY_POLICY_VERSION
    assert result["computational_experiment_id"].startswith("exp_")


def test_final_status_is_ready_only_when_all_materiality_gates_are_resolved() -> None:
    ready = classify_final_status(
        authenticity_match=True,
        checksum_match=True,
        conflicting_duplicates=0,
        trade_funding_critical_gaps=0,
        oos_critical_mark_gaps=0,
        all_differences_classified=True,
        candidate_materiality_resolved=True,
        pre_roll_identity_valid=True,
    )
    unresolved = classify_final_status(
        authenticity_match=True,
        checksum_match=True,
        conflicting_duplicates=0,
        trade_funding_critical_gaps=0,
        oos_critical_mark_gaps=0,
        all_differences_classified=False,
        candidate_materiality_resolved=True,
        pre_roll_identity_valid=True,
    )
    failed = classify_final_status(
        authenticity_match=False,
        checksum_match=True,
        conflicting_duplicates=0,
        trade_funding_critical_gaps=0,
        oos_critical_mark_gaps=0,
        all_differences_classified=True,
        candidate_materiality_resolved=True,
        pre_roll_identity_valid=True,
    )

    assert ready == "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
    assert unresolved == "DATA_MATERIALITY_UNRESOLVED"
    assert failed == "DATA_INTEGRITY_FAILED"


def test_candidate_materiality_summary_counts_direction_and_geometry_by_split() -> None:
    result = summarize_candidate_materiality(
        price_difference_bar_count=2,
        compared_decision_timestamps=10,
        details=[
            {
                "split": "VALIDATION",
                "indicator_value_changed": True,
                "trend_state_changed": False,
                "native_market_view": "NO_SETUP",
                "aggregated_market_view": "LONG",
                "stop_or_tp_changed": False,
            },
            {
                "split": "OOS",
                "indicator_value_changed": True,
                "trend_state_changed": False,
                "native_market_view": "LONG",
                "aggregated_market_view": "LONG",
                "stop_or_tp_changed": True,
            },
        ],
    )

    assert result["candidate_direction_changed"] == 1
    assert result["no_setup_to_setup"] == 1
    assert result["setup_to_no_setup"] == 0
    assert result["stop_or_tp_changed"] == 1
    assert result["affected_candidate_setups_by_split"] == {
        "TRAINING": 0,
        "VALIDATION": 1,
        "OOS": 1,
    }
    assert result["materiality_conclusion"] == "OFFICIAL_SOURCE_SENSITIVITY"


def test_quantized_stop_tp_uses_frozen_directional_tick_rules() -> None:
    assert quantized_stop_tp(
        side="LONG",
        target_open=Decimal("100"),
        atr=Decimal("10"),
        slippage=Decimal("0.0001"),
        tick=Decimal("0.1"),
    ) == (Decimal("80.1"), Decimal("130.1"))
    assert quantized_stop_tp(
        side="SHORT",
        target_open=Decimal("100"),
        atr=Decimal("10"),
        slippage=Decimal("0.0001"),
        tick=Decimal("0.1"),
    ) == (Decimal("119.9"), Decimal("69.9"))
