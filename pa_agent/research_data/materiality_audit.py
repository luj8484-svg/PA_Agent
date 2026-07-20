from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from pa_agent.research_data.canonical import canonical_dumps
from pa_agent.research_data.hashing import computational_experiment_id, dataset_content_hash

AUTHORITY_POLICY_VERSION = "BINANCE_OFFICIAL_SOURCE_AUTHORITY_V1"
MATERIALITY_SCHEMA_VERSION = "NATIVE_BAR_MATERIALITY_V1"
PRICE_FIELDS = frozenset({"open", "high", "low", "close"})
AUDIT_ONLY_FIELDS = frozenset(
    {
        "base_volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
        "trade_count",
    }
)
COMPARISON_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "base_volume",
    "quote_volume",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "trade_count",
)
TRAINING_START_MS = 1_601_510_400_000
VALIDATION_START_MS = 1_696_118_400_000
OOS_START_MS = 1_727_740_800_000


def _utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def decimal_difference(native: str | int, aggregated: str | int) -> dict[str, str]:
    native_decimal = Decimal(str(native))
    aggregated_decimal = Decimal(str(aggregated))
    absolute = abs(native_decimal - aggregated_decimal)
    denominator = max(abs(native_decimal), abs(aggregated_decimal))
    relative = Decimal(0) if denominator == 0 else absolute / denominator
    return {
        "absolute_difference": canonical_dumps(absolute).strip('"'),
        "relative_difference": canonical_dumps(relative).strip('"'),
    }


def classify_differences(fields: set[str] | frozenset[str]) -> str:
    if fields & PRICE_FIELDS:
        return "PRICE_DIFFERENCE"
    if fields and fields <= AUDIT_ONLY_FIELDS:
        return "AUDIT_ONLY_DIFFERENCE"
    return "STRUCTURAL_DIFFERENCE"


def bar_materiality_record(
    *,
    symbol: str,
    interval: str,
    native: Mapping[str, Any],
    aggregated: Mapping[str, Any],
    differing_field_names: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    differences = []
    for field in COMPARISON_FIELDS:
        if differing_field_names is not None and field not in differing_field_names:
            continue
        if Decimal(str(native[field])) == Decimal(str(aggregated[field])):
            continue
        differences.append(
            {
                "field": field,
                "native": str(native[field]),
                "aggregated": str(aggregated[field]),
                **decimal_difference(native[field], aggregated[field]),
            }
        )
    timestamp = int(native["open_time_utc_ms"])
    return {
        "schema_version": MATERIALITY_SCHEMA_VERSION,
        "authority_policy_version": AUTHORITY_POLICY_VERSION,
        "symbol": symbol,
        "interval": interval,
        "open_time_utc": datetime.fromtimestamp(timestamp / 1000, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "open_time_utc_ms": timestamp,
        "native_bar_hash": _sha256(native),
        "aggregated_bar_hash": _sha256(aggregated),
        "differing_fields": differences,
        "differing_field_count": len(differences),
        "materiality_category": classify_differences({item["field"] for item in differences}),
        "split": classify_split(timestamp),
    }


def classify_split(timestamp_utc_ms: int) -> str:
    if timestamp_utc_ms < TRAINING_START_MS:
        return "PRE_ROLL"
    if timestamp_utc_ms < VALIDATION_START_MS:
        return "TRAINING"
    if timestamp_utc_ms < OOS_START_MS:
        return "VALIDATION"
    return "OOS"


def mark_gap_evidence(*, symbol: str, start_utc: str, end_utc: str) -> dict[str, Any]:
    start_ms = _utc_ms(start_utc)
    end_ms = _utc_ms(end_utc)
    minute_count = (end_ms - start_ms + 1 + 59_999) // 60_000
    split = classify_split(start_ms)
    return {
        "symbol": symbol,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "minute_count": minute_count,
        "split": split,
        "is_oos": split == "OOS",
        "affects_candidate_decision": False,
        "candidate_reason": "2A authority inputs are native trade 4H and native trade 1D",
        "due_entry_intent_exists": None,
        "scheduled_exit_exists": None,
        "open_position_crosses": None,
        "affected_plan_count": None,
        "affected_trade_count": None,
        "trade_impact_status": "REQUIRES_2D_EPISODE_CONTEXT",
        "expected_2c_result": "INVALID_IF_ACTIVE_POSITION_OR_ECONOMIC_EVENT",
        "empty_context_result": "RECORDED_NOT_SYNTHESIZED_IF_FLAT_AND_NO_EVENT",
        "interpolation_used": False,
        "index_substitution_used": False,
        "forward_fill_used": False,
    }


def build_pre_roll_identity(
    *,
    records_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    data_bundle_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> dict[str, Any]:
    start_ms = _utc_ms("2020-01-01T00:00:00Z")
    training_start_ms = TRAINING_START_MS
    selected = {
        symbol: [
            record
            for record in records
            if start_ms <= int(record["open_time_utc_ms"]) < training_start_ms
        ]
        for symbol, records in sorted(records_by_symbol.items())
    }
    identity_records = [
        {"symbol": symbol, **record} for symbol, records in selected.items() for record in records
    ]
    pre_roll_hash = dataset_content_hash(
        identity_records,
        key_fields=("symbol", "open_time_utc_ms"),
    )
    strategy_data_identity = _sha256(
        {
            "authority_policy_version": AUTHORITY_POLICY_VERSION,
            "data_bundle_hash": data_bundle_hash,
            "pre_roll_content_hash": pre_roll_hash,
            "training_start_utc_ms": training_start_ms,
        }
    )
    experiment_id = computational_experiment_id(
        content_dependency_hashes={
            "strategy_data@STRATEGY_DATA_IDENTITY_V2": strategy_data_identity
        },
        experiment_scope="candidate",
        sample_start_utc_ms=training_start_ms,
        sample_end_utc_ms=_utc_ms("2026-03-31T23:59:59.999000Z"),
        strategy_version="BTC_ETH_PA_STRATEGY_V1_1",
        execution_version="NOT_EXECUTED_DATA_AUDIT",
        cost_version="NOT_EXECUTED_DATA_AUDIT",
        code_commit=code_commit,
        dependency_lock_version=dependency_lock_hash,
    )
    return {
        "version": "EXPERIMENT_SPLIT_CANDIDATE_V2",
        "minimum_required_pre_roll_1d_bars": 250,
        "actual_pre_roll_start_utc": "2020-01-01T00:00:00Z",
        "actual_pre_roll_end_utc": "2020-09-30T23:59:59.999000Z",
        "actual_pre_roll_1d_bars": {symbol: len(records) for symbol, records in selected.items()},
        "training_start_utc": "2020-10-01T00:00:00Z",
        "training_end_utc": "2023-09-30T23:59:59.999000Z",
        "validation_start_utc": "2023-10-01T00:00:00Z",
        "validation_end_utc": "2024-09-30T23:59:59.999000Z",
        "oos_start_utc": "2024-10-01T00:00:00Z",
        "oos_end_utc": "2026-03-31T23:59:59.999000Z",
        "authority_policy_version": AUTHORITY_POLICY_VERSION,
        "pre_roll_content_hash": pre_roll_hash,
        "strategy_data_identity": strategy_data_identity,
        "computational_experiment_id": experiment_id,
        "unassigned_read_periods": [],
    }


def summarize_candidate_materiality(
    *,
    price_difference_bar_count: int,
    compared_decision_timestamps: int,
    details: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    setups = {"LONG", "SHORT"}
    direction_changed = sum(
        item["native_market_view"] != item["aggregated_market_view"] for item in details
    )
    setup_to_no_setup = sum(
        item["native_market_view"] in setups and item["aggregated_market_view"] not in setups
        for item in details
    )
    no_setup_to_setup = sum(
        item["native_market_view"] not in setups and item["aggregated_market_view"] in setups
        for item in details
    )
    stop_or_tp_changed = sum(bool(item["stop_or_tp_changed"]) for item in details)
    affected_by_split = {"TRAINING": 0, "VALIDATION": 0, "OOS": 0}
    for item in details:
        if (
            item["native_market_view"] != item["aggregated_market_view"]
            or item["stop_or_tp_changed"]
        ) and item["split"] in affected_by_split:
            affected_by_split[item["split"]] += 1
    material = bool(direction_changed or stop_or_tp_changed)
    return {
        "schema_version": "CANDIDATE_MATERIALITY_REPORT_V1",
        "authority_policy_version": AUTHORITY_POLICY_VERSION,
        "native_is_formal_strategy_source": True,
        "aggregated_is_audit_only": True,
        "price_difference_bar_count": price_difference_bar_count,
        "compared_decision_timestamps": compared_decision_timestamps,
        "indicator_value_changed": sum(bool(item["indicator_value_changed"]) for item in details),
        "trend_state_changed": sum(bool(item["trend_state_changed"]) for item in details),
        "candidate_direction_changed": direction_changed,
        "setup_to_no_setup": setup_to_no_setup,
        "no_setup_to_setup": no_setup_to_setup,
        "entry_rule_changed": direction_changed,
        "stop_or_tp_changed": stop_or_tp_changed,
        "affected_candidate_setups_by_split": affected_by_split,
        "affected_trades_by_split": {"TRAINING": None, "VALIDATION": None, "OOS": None},
        "affected_trade_count_status": "REQUIRES_APPROVED_2D_EXECUTION_CONTEXT",
        "comparison_status": "COMPLETED_TARGETED_2A_PURE_FUNCTION_COMPARISON",
        "materiality_conclusion": (
            "OFFICIAL_SOURCE_SENSITIVITY" if material else "NON_MATERIAL_TO_STRATEGY_V1"
        ),
        "details": list(details),
        "full_2d_run": False,
    }


def quantized_stop_tp(
    *,
    side: str,
    target_open: Decimal,
    atr: Decimal,
    slippage: Decimal,
    tick: Decimal,
) -> tuple[Decimal, Decimal]:
    def floor_tick(value: Decimal) -> Decimal:
        return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick

    def ceil_tick(value: Decimal) -> Decimal:
        return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick

    if side == "LONG":
        entry = ceil_tick(target_open * (Decimal(1) + slippage))
        return ceil_tick(entry - Decimal(2) * atr), floor_tick(entry + Decimal(3) * atr)
    if side == "SHORT":
        entry = floor_tick(target_open * (Decimal(1) - slippage))
        return floor_tick(entry + Decimal(2) * atr), ceil_tick(entry - Decimal(3) * atr)
    raise ValueError("side must be LONG or SHORT")


def classify_final_status(
    *,
    authenticity_match: bool,
    checksum_match: bool,
    conflicting_duplicates: int,
    trade_funding_critical_gaps: int,
    oos_critical_mark_gaps: int,
    all_differences_classified: bool,
    candidate_materiality_resolved: bool,
    pre_roll_identity_valid: bool,
) -> str:
    if (
        not authenticity_match
        or not checksum_match
        or conflicting_duplicates
        or trade_funding_critical_gaps
        or oos_critical_mark_gaps
    ):
        return "DATA_INTEGRITY_FAILED"
    if not (
        all_differences_classified and candidate_materiality_resolved and pre_roll_identity_valid
    ):
        return "DATA_MATERIALITY_UNRESOLVED"
    return "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
