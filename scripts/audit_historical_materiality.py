from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from bisect import bisect_right
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pa_agent.research_backtest.domain.enums import TrendState
from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.donchian import previous_donchian
from pa_agent.research_backtest.indicators.ema import ema
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
from pa_agent.research_data.canonical import canonical_dumps
from pa_agent.research_data.materiality_audit import (
    AUTHORITY_POLICY_VERSION,
    bar_materiality_record,
    build_pre_roll_identity,
    classify_final_status,
    classify_split,
    mark_gap_evidence,
    quantized_stop_tp,
    summarize_candidate_materiality,
)
from pa_agent.research_data.validation import ABSOLUTE_TOLERANCES, RELATIVE_TOLERANCE

SYMBOLS = ("BTCUSDT", "ETHUSDT")
INTERVALS = {"4h": (14_400_000, "trade_4h"), "1d": (86_400_000, "trade_1d")}
EXACT_FIELDS = ("open", "high", "low", "close", "trade_count")


def read_records(root: Path, symbol: str, stream: str):
    for path in sorted((root / "data" / "canonical" / symbol / stream).glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def aggregate_trade_1m(root: Path, symbol: str) -> dict[str, dict[int, dict[str, Any]]]:
    outputs: dict[str, dict[int, dict[str, Any]]] = {"4h": {}, "1d": {}}
    for record in read_records(root, symbol, "trade_1m"):
        timestamp = int(record["open_time_utc_ms"])
        for interval, (interval_ms, _native_name) in INTERVALS.items():
            bucket = timestamp // interval_ms * interval_ms
            current = outputs[interval].get(bucket)
            if current is None:
                current = {
                    "open_time_utc_ms": bucket,
                    "close_time_utc_ms": bucket + interval_ms - 1,
                    "open": str(record["open"]),
                    "high": str(record["high"]),
                    "low": str(record["low"]),
                    "close": str(record["close"]),
                    "base_volume": "0",
                    "quote_volume": "0",
                    "trade_count": 0,
                    "taker_buy_base_volume": "0",
                    "taker_buy_quote_volume": "0",
                    "source_1m_count": 0,
                }
                outputs[interval][bucket] = current
            current["high"] = str(max(Decimal(current["high"]), Decimal(record["high"])))
            current["low"] = str(min(Decimal(current["low"]), Decimal(record["low"])))
            current["close"] = str(record["close"])
            for field in ABSOLUTE_TOLERANCES:
                current[field] = str(Decimal(current[field]) + Decimal(record[field]))
            current["trade_count"] += int(record["trade_count"])
            current["source_1m_count"] += 1
    return outputs


def volume_matches(left: Any, right: Any, absolute_tolerance: Decimal) -> bool:
    left_decimal = Decimal(str(left))
    right_decimal = Decimal(str(right))
    difference = abs(left_decimal - right_decimal)
    if difference <= absolute_tolerance:
        return True
    denominator = max(abs(left_decimal), abs(right_decimal))
    return denominator != 0 and difference / denominator <= RELATIVE_TOLERANCE


def issue_fields(native: dict[str, Any], aggregated: dict[str, Any]) -> set[str]:
    result = {
        field
        for field in EXACT_FIELDS
        if Decimal(str(native[field])) != Decimal(str(aggregated[field]))
    }
    result.update(
        field
        for field, tolerance in ABSOLUTE_TOLERANCES.items()
        if not volume_matches(native[field], aggregated[field], tolerance)
    )
    return result


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_dumps(value) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def file_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if path.exists():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def trend_state(daily_close: Decimal, ema50: Decimal, ema200: Decimal) -> TrendState:
    if daily_close > ema200 and ema50 > ema200:
        return TrendState.BULL
    if daily_close < ema200 and ema50 < ema200:
        return TrendState.BEAR
    return TrendState.NEUTRAL


def load_target_open(
    output: Path,
    symbol: str,
    target_time_utc_ms: int,
    cache: dict[tuple[str, str], dict[int, Decimal]],
) -> Decimal:
    month = datetime.fromtimestamp(target_time_utc_ms / 1000, tz=UTC).strftime("%Y-%m")
    key = (symbol, month)
    if key not in cache:
        path = output / "data" / "canonical" / symbol / "trade_1m" / f"{month}.jsonl"
        with path.open(encoding="utf-8") as handle:
            cache[key] = {
                int(record["open_time_utc_ms"]): Decimal(record["open"])
                for line in handle
                if line.strip()
                for record in (json.loads(line),)
            }
    return cache[key][target_time_utc_ms]


def current_contract_ticks() -> tuple[dict[str, Decimal], str]:
    snapshots = sorted(
        Path("artifacts/data_readiness/refreshed").glob("*/canonical/contract_rules_current.jsonl")
    )
    if not snapshots:
        raise FileNotFoundError("audited current contract-rule snapshot is unavailable")
    records = [json.loads(line) for line in snapshots[-1].read_text(encoding="utf-8").splitlines()]
    return (
        {record["symbol"]: Decimal(record["price_tick"]) for record in records},
        records[0]["source_hash"],
    )


def compare_candidate_materiality(
    output: Path,
    materiality_rows: list[dict[str, Any]],
    aggregated_cache: dict[str, dict[str, dict[int, dict[str, Any]]]],
) -> dict[str, Any]:
    price_rows = [
        row for row in materiality_rows if row["materiality_category"] == "PRICE_DIFFERENCE"
    ]
    details: list[dict[str, Any]] = []
    compared_timestamps = 0
    ticks, contract_source_hash = current_contract_ticks()
    slippage = {"BTCUSDT": Decimal("0.0001"), "ETHUSDT": Decimal("0.0002")}
    target_open_cache: dict[tuple[str, str], dict[int, Decimal]] = {}
    price_times_by_symbol = {
        symbol: {
            int(row["open_time_utc_ms"])
            for row in price_rows
            if row["symbol"] == symbol and row["interval"] == "4h"
        }
        for symbol in SYMBOLS
    }
    for symbol in SYMBOLS:
        price_times = price_times_by_symbol[symbol]
        if not price_times:
            continue
        native = list(read_records(output, symbol, "trade_4h"))
        aggregated = aggregated_cache[symbol]["4h"]
        audit = [aggregated[int(record["open_time_utc_ms"])] for record in native]
        native_highs = [Decimal(record["high"]) for record in native]
        native_lows = [Decimal(record["low"]) for record in native]
        native_closes = [Decimal(record["close"]) for record in native]
        audit_highs = [Decimal(record["high"]) for record in audit]
        audit_lows = [Decimal(record["low"]) for record in audit]
        audit_closes = [Decimal(record["close"]) for record in audit]
        native_atr = wilder_atr(native_highs, native_lows, native_closes, 14)
        audit_atr = wilder_atr(audit_highs, audit_lows, audit_closes, 14)

        daily = list(read_records(output, symbol, "trade_1d"))
        daily_closes = [Decimal(record["close"]) for record in daily]
        daily_close_times = [int(record["close_time_utc_ms"]) for record in daily]
        ema50 = ema(daily_closes, 50)
        ema200 = ema(daily_closes, 200)
        for index in range(20, len(native)):
            timestamp = int(native[index]["open_time_utc_ms"])
            decision_time = int(native[index]["close_time_utc_ms"])
            if timestamp < 1_601_510_400_000 or timestamp > 1_775_001_599_999:
                continue
            native_atr_value = native_atr[index]
            audit_atr_value = audit_atr[index]
            if native_atr_value is None or audit_atr_value is None:
                continue
            native_atr_decimal = float64_to_decimal_15sig(native_atr_value)
            audit_atr_decimal = float64_to_decimal_15sig(audit_atr_value)
            native_donchian = previous_donchian(native_highs, native_lows, index=index, lookback=20)
            audit_donchian = previous_donchian(audit_highs, audit_lows, index=index, lookback=20)
            economic_input_changed = (
                native_atr_decimal != audit_atr_decimal
                or native_donchian != audit_donchian
                or native_closes[index] != audit_closes[index]
            )
            if not economic_input_changed and timestamp not in price_times:
                continue
            compared_timestamps += 1
            daily_index = bisect_right(daily_close_times, decision_time) - 1
            if daily_index < 199 or ema50[daily_index] is None or ema200[daily_index] is None:
                continue
            ema50_decimal = float64_to_decimal_15sig(ema50[daily_index])
            ema200_decimal = float64_to_decimal_15sig(ema200[daily_index])
            trend = trend_state(daily_closes[daily_index], ema50_decimal, ema200_decimal)
            native_market = classify_market(
                trend_state=trend,
                current_close=native_closes[index],
                donchian_high=native_donchian[0],
                donchian_low=native_donchian[1],
            )
            audit_market = classify_market(
                trend_state=trend,
                current_close=audit_closes[index],
                donchian_high=audit_donchian[0],
                donchian_low=audit_donchian[1],
            )
            native_view = native_market.market_view.value
            audit_view = audit_market.market_view.value
            actionable = {"LONG", "SHORT"}
            geometry_changed = native_view != audit_view and (
                native_view in actionable or audit_view in actionable
            )
            native_geometry = audit_geometry = None
            target_execution_time = decision_time + 1 + 60_000
            if native_view == audit_view and native_view in actionable:
                target_open = load_target_open(
                    output, symbol, target_execution_time, target_open_cache
                )
                native_geometry = quantized_stop_tp(
                    side=native_view,
                    target_open=target_open,
                    atr=native_atr_decimal,
                    slippage=slippage[symbol],
                    tick=ticks[symbol],
                )
                audit_geometry = quantized_stop_tp(
                    side=audit_view,
                    target_open=target_open,
                    atr=audit_atr_decimal,
                    slippage=slippage[symbol],
                    tick=ticks[symbol],
                )
                geometry_changed = native_geometry != audit_geometry
            details.append(
                {
                    "symbol": symbol,
                    "decision_time_utc_ms": decision_time,
                    "decision_bar_open_time_utc_ms": timestamp,
                    "split": classify_split(timestamp),
                    "native_atr14_4h": str(native_atr_decimal),
                    "aggregated_atr14_4h": str(audit_atr_decimal),
                    "native_donchian_high": str(native_donchian[0]),
                    "aggregated_donchian_high": str(audit_donchian[0]),
                    "native_donchian_low": str(native_donchian[1]),
                    "aggregated_donchian_low": str(audit_donchian[1]),
                    "native_market_view": native_view,
                    "aggregated_market_view": audit_view,
                    "indicator_value_changed": economic_input_changed,
                    "trend_state_changed": False,
                    "stop_or_tp_changed": geometry_changed,
                    "target_execution_time_utc_ms": target_execution_time,
                    "native_stop_tp": (
                        [str(value) for value in native_geometry]
                        if native_geometry is not None
                        else None
                    ),
                    "aggregated_stop_tp": (
                        [str(value) for value in audit_geometry]
                        if audit_geometry is not None
                        else None
                    ),
                    "stop_tp_comparison_basis": "SLIPPAGE_MODEL_V1_CURRENT_APPROX_TICK_QUANTIZED",
                }
            )
    result = summarize_candidate_materiality(
        price_difference_bar_count=len(price_rows),
        compared_decision_timestamps=compared_timestamps,
        details=details,
    )
    result["geometry_model"] = {
        "execution_delay_minutes": 1,
        "slippage_model_version": "SLIPPAGE_MODEL_V1",
        "slippage_rate": {symbol: str(value) for symbol, value in slippage.items()},
        "contract_rule_version": "APPROXIMATED_CURRENT_RULES_V1",
        "contract_rule_source_hash": contract_source_hash,
        "tick_size": {symbol: str(value) for symbol, value in ticks.items()},
        "watermark": "NOT_EXCHANGE_EXACT",
    }
    return result


def run(output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    materiality_rows: list[dict[str, Any]] = []
    compared: dict[str, dict[str, int]] = {}
    aggregated_cache: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    for symbol in SYMBOLS:
        compared[symbol] = {}
        aggregated_by_interval = aggregate_trade_1m(output, symbol)
        aggregated_cache[symbol] = aggregated_by_interval
        for interval, (interval_ms, native_name) in INTERVALS.items():
            aggregated = aggregated_by_interval[interval]
            native = {
                int(record["open_time_utc_ms"]): record
                for record in read_records(output, symbol, native_name)
            }
            compared[symbol][interval] = len(set(native) & set(aggregated))
            expected_count = interval_ms // 60_000
            for timestamp in sorted(set(native) & set(aggregated)):
                left = aggregated[timestamp]
                right = native[timestamp]
                if left["source_1m_count"] != expected_count:
                    continue
                fields = issue_fields(right, left)
                if fields:
                    materiality_rows.append(
                        bar_materiality_record(
                            symbol=symbol,
                            interval=interval,
                            native=right,
                            aggregated=left,
                            differing_field_names=fields,
                        )
                    )

    materiality_path = output / "native_bar_materiality.jsonl"
    materiality_path.write_text(
        "".join(canonical_dumps(row) + "\n" for row in materiality_rows),
        encoding="utf-8",
        newline="\n",
    )
    category_counts = Counter(row["materiality_category"] for row in materiality_rows)
    field_counts = Counter(
        difference["field"] for row in materiality_rows for difference in row["differing_fields"]
    )
    split_counts = Counter(row["split"] for row in materiality_rows)
    symbol_interval_counts = Counter(
        (row["symbol"], row["interval"], row["materiality_category"]) for row in materiality_rows
    )
    split_category_counts = Counter(
        (row["split"], row["materiality_category"]) for row in materiality_rows
    )
    summary = {
        "schema_version": "NATIVE_BAR_MATERIALITY_SUMMARY_V1",
        "authority_policy": {
            "version": AUTHORITY_POLICY_VERSION,
            "candidate_inputs": ["BINANCE_NATIVE_TRADE_4H", "BINANCE_NATIVE_TRADE_1D"],
            "execution_inputs": ["BINANCE_TRADE_1M", "BINANCE_MARK_1M", "BINANCE_FUNDING"],
            "index_1m_role": "AUDIT_ONLY",
            "aggregated_4h_1d_role": "CROSS_VALIDATION_AND_SENSITIVITY_ONLY",
            "disagreement_class": "OFFICIAL_SOURCE_PRODUCT_DISAGREEMENT",
            "local_corruption_claimed": False,
        },
        "compared_bars": compared,
        "issue_bar_count": len(materiality_rows),
        "differing_field_count": sum(field_counts.values()),
        "prior_303_semantics": "DIFFERING_FIELD_COUNT_NOT_BAR_COUNT",
        "audit_only_bar_count": category_counts["AUDIT_ONLY_DIFFERENCE"],
        "price_difference_bar_count": category_counts["PRICE_DIFFERENCE"],
        "structural_difference_bar_count": category_counts["STRUCTURAL_DIFFERENCE"],
        "field_counts": dict(sorted(field_counts.items())),
        "by_split": dict(sorted(split_counts.items())),
        "by_split_category": [
            {"split": key[0], "category": key[1], "count": value}
            for key, value in sorted(split_category_counts.items())
        ],
        "by_symbol_interval_category": [
            {"symbol": key[0], "interval": key[1], "category": key[2], "count": value}
            for key, value in sorted(symbol_interval_counts.items())
        ],
        "complete_issue_report_hash": hashlib.sha256(materiality_path.read_bytes()).hexdigest(),
    }
    write_json(output / "native_bar_materiality_summary.json", summary)

    price_count = summary["price_difference_bar_count"]
    candidate = compare_candidate_materiality(output, materiality_rows, aggregated_cache)
    write_json(output / "candidate_materiality_report.json", candidate)

    historical_gaps = json.loads(
        (output / "historical_gap_report.json").read_text(encoding="utf-8")
    )
    mark_rows = [
        mark_gap_evidence(
            symbol=symbol,
            start_utc=interval["start_utc"],
            end_utc=interval["end_utc"],
        )
        for symbol in SYMBOLS
        for interval in historical_gaps[symbol]["mark_1m"]["gap_intervals"]
    ]
    mark_split_counts = Counter(row["split"] for row in mark_rows)
    mark_report = {
        "schema_version": "MARK_GAP_MATERIALITY_V1",
        "rules": {
            "interpolation": "FORBIDDEN",
            "index_substitution": "FORBIDDEN",
            "forward_fill": "FORBIDDEN",
            "active_context": "PATH_OR_EPISODE_INVALID",
            "flat_no_event_context": "RECORD_GAP_WITHOUT_SYNTHETIC_RESULT",
        },
        "gap_count": len(mark_rows),
        "minute_count": sum(row["minute_count"] for row in mark_rows),
        "by_split": dict(sorted(mark_split_counts.items())),
        "oos_critical_mark_gap_count": sum(row["is_oos"] for row in mark_rows),
        "training_affected_trade_count": None,
        "validation_affected_trade_count": None,
        "trade_count_status": "REQUIRES_APPROVED_2D_EPISODE_CONTEXT_NOT_SILENTLY_REMOVED",
        "gaps": mark_rows,
    }
    write_json(output / "mark_gap_materiality.json", mark_report)

    records_by_symbol = {
        symbol: list(read_records(output, symbol, "trade_1d")) for symbol in SYMBOLS
    }
    prior_final = json.loads(
        (output / "final_data_readiness_report.json").read_text(encoding="utf-8")
    )
    code_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dependency_hash = file_hash([Path("pyproject.toml"), Path("uv.lock")])
    split_v2 = build_pre_roll_identity(
        records_by_symbol=records_by_symbol,
        data_bundle_hash=prior_final["data_bundle_hash"],
        code_commit=code_commit,
        dependency_lock_hash=dependency_hash,
    )
    write_json(output / "experiment_split_candidate_v2.json", split_v2)

    annual = json.loads((output / "annual_sample_reconciliation.json").read_text(encoding="utf-8"))
    authenticity_match = annual["totals"] == {
        "matched": 588,
        "mismatched": 0,
        "missing_from_remote": 0,
        "missing_from_local": 0,
    }
    checksum_match = all(
        historical_gaps[symbol][stream]["all_raw_checksums_match"]
        for symbol in SYMBOLS
        for stream in ("trade_1m", "mark_1m", "trade_4h", "trade_1d", "funding")
    )
    conflicting_duplicates = sum(
        historical_gaps[symbol][stream]["conflicting_duplicate_count"]
        for symbol in SYMBOLS
        for stream in ("trade_1m", "mark_1m", "trade_4h", "trade_1d", "funding")
    )
    trade_funding_gaps = sum(
        historical_gaps[symbol][stream]["gap_count"]
        for symbol in SYMBOLS
        for stream in ("trade_1m", "funding")
    )
    pre_roll_valid = all(value >= 250 for value in split_v2["actual_pre_roll_1d_bars"].values())
    status = classify_final_status(
        authenticity_match=authenticity_match,
        checksum_match=checksum_match,
        conflicting_duplicates=conflicting_duplicates,
        trade_funding_critical_gaps=trade_funding_gaps,
        oos_critical_mark_gaps=mark_report["oos_critical_mark_gap_count"],
        all_differences_classified=summary["structural_difference_bar_count"] == 0,
        candidate_materiality_resolved=candidate["comparison_status"]
        == "COMPLETED_TARGETED_2A_PURE_FUNCTION_COMPARISON",
        pre_roll_identity_valid=pre_roll_valid,
    )
    final = {
        "schema_version": "FINAL_DATA_MATERIALITY_REPORT_V1",
        "final_status": status,
        "two_d_authorization": (
            "CLEAN_OOS_BASELINE_AND_DISCLOSED_DIAGNOSTICS_ONLY"
            if status == "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
            else "NOT_AUTHORIZED"
        ),
        "authority_policy": summary["authority_policy"],
        "native_bar_materiality_summary": summary,
        "candidate_materiality": candidate,
        "mark_gap_materiality": mark_report,
        "experiment_split_candidate_v2": split_v2,
        "authenticity_totals": annual["totals"],
        "checksum_match": checksum_match,
        "conflicting_duplicate_count": conflicting_duplicates,
        "trade_funding_critical_gap_count": trade_funding_gaps,
        "permanent_watermarks": [
            "APPROXIMATED_EXECUTION_INFRASTRUCTURE",
            "OFFICIAL_SOURCE_PRODUCT_DISAGREEMENT",
            "NOT_EXCHANGE_EXACT",
            "NOT_LIVE_ELIGIBLE",
        ],
        "scope_attestation": {
            "historical_redownloaded": False,
            "modified_2a_2b_2c": False,
            "full_2d_run": False,
            "api_key_used": False,
            "trading_capability_used": False,
        },
    }
    write_json(output / "final_materiality_report.json", final)
    prior_final.setdefault("pre_materiality_reclassification_status", prior_final["final_status"])
    prior_final["final_status"] = status
    prior_final["two_d_authorized"] = status == (
        "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
    )
    prior_final["authority_policy"] = summary["authority_policy"]
    prior_final["materiality_reclassification"] = {
        "schema_version": final["schema_version"],
        "report": "final_materiality_report.json",
        "issue_bar_count": summary["issue_bar_count"],
        "differing_field_count": summary["differing_field_count"],
        "audit_only_bar_count": summary["audit_only_bar_count"],
        "price_difference_bar_count": summary["price_difference_bar_count"],
        "candidate_direction_changed": candidate["candidate_direction_changed"],
        "stop_or_tp_changed": candidate["stop_or_tp_changed"],
        "oos_critical_mark_gap_count": mark_report["oos_critical_mark_gap_count"],
    }
    prior_final["required_permanent_labels"] = final["permanent_watermarks"]
    prior_final["experiment_split_candidate"] = split_v2
    write_json(output / "final_data_readiness_report.json", prior_final)
    data_readiness_markdown = f"""# Binance Historical Data Readiness

Final status after materiality reclassification: `{status}`

- Pre-materiality status: `DATA_INTEGRITY_FAILED` (preserved as coarse audit history only).
- Authority policy: `{AUTHORITY_POLICY_VERSION}`; native 4H/1D is the 2A source, aggregated 4H/1D is audit-only.
- Issue bars: `{summary["issue_bar_count"]}`; differing fields: `{summary["differing_field_count"]}`.
- Audit-only bars: `{summary["audit_only_bar_count"]}`; price-difference bars: `{price_count}`.
- Candidate direction changes: `{candidate["candidate_direction_changed"]}`; quantized stop/TP changes: `{candidate["stop_or_tp_changed"]}`.
- OOS critical mark gaps: `{mark_report["oos_critical_mark_gap_count"]}`.
- Full evidence: `final_materiality_report.json`.
- Permanent watermarks: `{", ".join(final["permanent_watermarks"])}`.
- No historical redownload, no 2A/2B/2C modification, no full 2D, no API key or trading capability.
"""
    (output / "final_data_readiness_report.md").write_text(
        data_readiness_markdown, encoding="utf-8", newline="\n"
    )
    markdown = f"""# Historical Data Materiality Reclassification

Final status: `{status}`

- Official-source disagreement issue bars: `{summary["issue_bar_count"]}`
- Differing fields: `{summary["differing_field_count"]}` (the prior `303` count is fields, not bars)
- Audit-only bars: `{summary["audit_only_bar_count"]}`
- Price-difference bars: `{price_count}`
- Candidate direction changes: `{candidate["candidate_direction_changed"]}`
- Stop/TP changes: `{candidate["stop_or_tp_changed"]}`
- OOS critical mark gaps: `{mark_report["oos_critical_mark_gap_count"]}`
- Actual pre-roll bars: `{canonical_dumps(split_v2["actual_pre_roll_1d_bars"])}`
- Pre-roll content hash: `{split_v2["pre_roll_content_hash"]}`
- Authority: native Binance trade 4H/1D for 2A; Binance trade 1m, mark 1m and funding for 2C; index is audit-only.
- No historical redownload, no 2A/2B/2C modification, no full 2D, no API key or trading capability.
"""
    (output / "final_materiality_report.md").write_text(markdown, encoding="utf-8", newline="\n")
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
