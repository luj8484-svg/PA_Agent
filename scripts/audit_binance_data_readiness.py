from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pa_agent.research_data.binance_public import (
    PUBLIC_BASE_URL,
    PUBLIC_PATHS,
    BinancePublicClient,
)
from pa_agent.research_data.canonical import canonical_dumps
from pa_agent.research_data.cli import _download_funding, _download_klines
from pa_agent.research_data.downloader import DatasetDownloader
from pa_agent.research_data.gaps import (
    FUNDING_SCHEDULE_VERSION,
    detect_funding_gap_intervals,
    detect_gap_intervals,
)
from pa_agent.research_data.hashing import (
    ACQUISITION_BUNDLE_CONTENT_VERSION,
    acquisition_manifest_hash,
    acquisition_run_id,
    dataset_content_hash,
    versioned_content_bundle_hash,
)
from pa_agent.research_data.models import CONTRACT_RULE_SCHEMA_VERSION
from pa_agent.research_data.normalize import normalize_contract_rules
from pa_agent.research_data.storage import AtomicDatasetStore

ONE_MINUTE_MS = 60_000
FOUR_HOURS_MS = 4 * 60 * ONE_MINUTE_MS
ONE_DAY_MS = 24 * 60 * ONE_MINUTE_MS
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SAMPLE_SEED = 20260719
SAMPLE_RULE_VERSION = "SHA256_LOWEST_RANK_BY_SEED_NAMESPACE_TIMESTAMP_V1"
AUDIT_SCHEMA_VERSION = "BINANCE_DATA_READINESS_AUDIT_V1"
FINAL_STATUSES = {
    "READY_FOR_BASELINE_EVALUATION",
    "STALE_DATA_REFRESH_REQUIRED",
    "DATA_COVERAGE_INSUFFICIENT",
    "DATA_INTEGRITY_FAILED",
    "SOURCE_UNAVAILABLE",
}


def latest_closed_boundaries(server_time_utc_ms: int) -> dict[str, dict[str, int]]:
    if server_time_utc_ms < 0:
        raise ValueError("server_time_utc_ms must be nonnegative")
    result: dict[str, dict[str, int]] = {}
    for interval, interval_ms in (
        ("1m", ONE_MINUTE_MS),
        ("4h", FOUR_HOURS_MS),
        ("1d", ONE_DAY_MS),
    ):
        current_open = (server_time_utc_ms // interval_ms) * interval_ms
        latest_open = current_open - interval_ms
        if latest_open < 0:
            raise ValueError("server time does not contain a fully closed interval")
        result[interval] = {
            "open_time_utc_ms": latest_open,
            "close_time_utc_ms": current_open - 1,
        }
    return result


def deterministic_sample(
    records: Sequence[Mapping[str, Any]],
    *,
    count: int,
    seed: int,
    namespace: str,
    timestamp_field: str,
) -> tuple[Mapping[str, Any], ...]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    if len(records) < count:
        raise ValueError(f"INSUFFICIENT_SAMPLE_RECORDS: required={count} available={len(records)}")
    ranked = sorted(
        records,
        key=lambda record: hashlib.sha256(
            f"{seed}|{namespace}|{int(record[timestamp_field])}".encode()
        ).hexdigest(),
    )
    selected = ranked[:count]
    return tuple(sorted(selected, key=lambda record: int(record[timestamp_field])))


def merge_records(
    old_records: Sequence[Mapping[str, Any]],
    new_records: Sequence[Mapping[str, Any]],
    *,
    key_field: str,
) -> tuple[tuple[Mapping[str, Any], ...], int]:
    merged: dict[int, Mapping[str, Any]] = {}
    canonical_by_key: dict[int, str] = {}
    duplicate_count = 0
    for record in (*old_records, *new_records):
        key = int(record[key_field])
        canonical = canonical_dumps(record)
        if key in merged:
            duplicate_count += 1
            if canonical_by_key[key] != canonical:
                raise ValueError(f"CONFLICTING_DUPLICATE: {key_field}={key}")
            continue
        merged[key] = record
        canonical_by_key[key] = canonical
    return tuple(merged[key] for key in sorted(merged)), duplicate_count


def classify_freshness(*, data_lag_minutes: int, data_lag_4h_bars: int) -> str:
    if data_lag_minutes < 0 or data_lag_4h_bars < 0:
        raise ValueError("data lag cannot be negative")
    if data_lag_minutes >= 24 * 60:
        return "SEVERELY_STALE"
    if data_lag_4h_bars >= 1:
        return "STALE"
    return "FRESH"


def coverage_day_metrics(common_start_ms: int, common_end_ms: int) -> dict[str, Any]:
    duration_ms = max(0, common_end_ms - common_start_ms)
    duration_days = Decimal(duration_ms) / Decimal(ONE_DAY_MS)
    required_days = Decimal(66) * Decimal("365.2425") / Decimal(12)
    return {
        "joint_common_duration_days": format(duration_days, "f"),
        "required_approximate_days": format(required_days, ".6f"),
        "sufficient": duration_days >= required_days,
    }


def utc_text(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000, tz=UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"Canonical record is not an object: {path}")
                records.append(value)
    return records


def max_download_timestamp(value: Any) -> int | None:
    found: list[int] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if (
                    key in {"downloaded_at_utc_ms", "completed_at_utc_ms"}
                    and isinstance(nested, int)
                    and not isinstance(nested, bool)
                ):
                    found.append(nested)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return max(found) if found else None


def discover_snapshots(search_root: Path) -> tuple[Path, list[dict[str, Any]]]:
    snapshots: list[dict[str, Any]] = []
    for summary_path in search_root.rglob("summary.json"):
        root = summary_path.parent
        required = (root / "acquisition_manifest.json", root / "canonical", root / "manifests")
        complete = all(path.exists() for path in required)
        snapshots.append(
            {
                "root": str(root.resolve()),
                "summary_path": str(summary_path.resolve()),
                "summary_modified_utc": utc_text(int(summary_path.stat().st_mtime * 1_000)),
                "complete_layout": complete,
                "canonical_bytes": sum(
                    item.stat().st_size for item in (root / "canonical").glob("*.jsonl")
                )
                if (root / "canonical").is_dir()
                else 0,
            }
        )
    complete = [item for item in snapshots if item["complete_layout"]]
    if not complete:
        raise FileNotFoundError("No complete research-data snapshot found")
    selected = max(
        complete,
        key=lambda item: (item["summary_modified_utc"], item["canonical_bytes"], item["root"]),
    )
    return Path(selected["root"]), sorted(snapshots, key=lambda item: item["root"])


def dataset_specs(symbol: str) -> tuple[dict[str, Any], ...]:
    return (
        {
            "name": f"{symbol}_trade_1m",
            "stream": "trade",
            "interval": "1m",
            "step": ONE_MINUTE_MS,
            "key": "open_time_utc_ms",
        },
        {
            "name": f"{symbol}_mark_1m",
            "stream": "mark",
            "interval": "1m",
            "step": ONE_MINUTE_MS,
            "key": "open_time_utc_ms",
        },
        {
            "name": f"{symbol}_index_1m",
            "stream": "index",
            "interval": "1m",
            "step": ONE_MINUTE_MS,
            "key": "open_time_utc_ms",
        },
        {
            "name": f"{symbol}_trade_4h",
            "stream": "trade",
            "interval": "4h",
            "step": FOUR_HOURS_MS,
            "key": "open_time_utc_ms",
        },
        {
            "name": f"{symbol}_trade_1d",
            "stream": "trade",
            "interval": "1d",
            "step": ONE_DAY_MS,
            "key": "open_time_utc_ms",
        },
        {
            "name": f"{symbol}_funding",
            "stream": "funding",
            "interval": None,
            "step": None,
            "key": "funding_time_utc_ms",
        },
    )


def duplicate_count(records: Sequence[Mapping[str, Any]], key: str) -> int:
    return len(records) - len({int(record[key]) for record in records})


def inventory_snapshot(root: Path, server_time_ms: int) -> dict[str, Any]:
    summary = read_json(root / "summary.json")
    acquisition = read_json(root / "acquisition_manifest.json")
    symbols: dict[str, Any] = {}
    for symbol in SYMBOLS:
        datasets: dict[str, Any] = {}
        for spec in dataset_specs(symbol):
            path = root / "canonical" / f"{spec['name']}.jsonl"
            records = read_jsonl(path)
            key = spec["key"]
            times = [int(record[key]) for record in records]
            manifest_path = root / "manifests" / f"{spec['name']}.json"
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
            unclosed = 0
            if spec["interval"] is not None:
                unclosed = sum(
                    not bool(record.get("is_closed"))
                    or int(record["close_time_utc_ms"]) >= server_time_ms
                    for record in records
                )
            datasets[spec["name"].removeprefix(f"{symbol}_")] = {
                "canonical_path": str(path.resolve()),
                "start_time_utc": utc_text(min(times) if times else None),
                "end_time_utc": utc_text(max(times) if times else None),
                "end_close_time_utc": utc_text(
                    max(int(record.get("close_time_utc_ms", record[key])) for record in records)
                    if records
                    else None
                ),
                "record_count": len(records),
                "duplicate_record_count": duplicate_count(records, key),
                "unclosed_kline_count": unclosed,
                "dataset_content_hash_stored": manifest.get("dataset_content_hash"),
                "dataset_content_hash_recomputed": dataset_content_hash(
                    records, key_fields=("symbol", key)
                ),
                "download_completed_at_utc": utc_text(manifest.get("completed_at_utc_ms")),
            }
        symbols[symbol] = datasets
    return {
        "selected_snapshot_root": str(root.resolve()),
        "source_server_time_utc": utc_text(summary.get("source_server_time_utc_ms")),
        "download_time_utc": utc_text(max_download_timestamp(summary)),
        "dataset_content_hash": summary.get("dataset_content_hash"),
        "acquisition_manifest_hash": summary.get("acquisition_manifest_hash"),
        "acquisition_run_id": acquisition.get("acquisition_run_id"),
        "contract_rule": summary.get("contract_rule_snapshot")
        or summary.get("contract_rule_manifest"),
        "maintenance_evidence": {
            "status": "ABSENT",
            "reason": "No versioned historical maintenance-margin evidence in first-batch snapshot",
        },
        "symbols": symbols,
    }


def connectivity_check(client: BinancePublicClient, server_time: int) -> dict[str, Any]:
    boundary = latest_closed_boundaries(server_time)
    probes = (
        ("/fapi/v1/time", {}),
        (
            "/fapi/v1/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": boundary["1m"]["open_time_utc_ms"],
                "endTime": boundary["1m"]["close_time_utc_ms"],
                "limit": 1,
            },
        ),
        (
            "/fapi/v1/markPriceKlines",
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": boundary["1m"]["open_time_utc_ms"],
                "endTime": boundary["1m"]["close_time_utc_ms"],
                "limit": 1,
            },
        ),
        (
            "/fapi/v1/indexPriceKlines",
            {
                "pair": "BTCUSDT",
                "interval": "1m",
                "startTime": boundary["1m"]["open_time_utc_ms"],
                "endTime": boundary["1m"]["close_time_utc_ms"],
                "limit": 1,
            },
        ),
        ("/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 1}),
        ("/fapi/v1/exchangeInfo", {}),
    )
    endpoints: list[dict[str, Any]] = []
    for path, params in probes:
        started = time.time_ns()
        payload = client.get_json(path, params)
        endpoints.append(
            {
                "method": "GET",
                "base_url": PUBLIC_BASE_URL,
                "path": path,
                "params": params,
                "success": True,
                "response_type": "array" if isinstance(payload, list) else "object",
                "response_count": len(payload) if isinstance(payload, list) else 1,
                "elapsed_ms": (time.time_ns() - started) // 1_000_000,
            }
        )
    return {
        "base_url": PUBLIC_BASE_URL,
        "allowlisted_paths": sorted(PUBLIC_PATHS),
        "authentication_used": False,
        "server_time_utc_ms": server_time,
        "server_time_utc": utc_text(server_time),
        "endpoints": endpoints,
    }


def freshness_report(local: dict[str, Any], server_time: int) -> dict[str, Any]:
    boundaries = latest_closed_boundaries(server_time)
    per_symbol: dict[str, Any] = {}
    for symbol in SYMBOLS:
        datasets = local["symbols"][symbol]
        latest_1m = int(
            datetime.fromisoformat(
                datasets["trade_1m"]["start_time_utc"].replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
        # End is the last open time; parse it rather than the close label.
        latest_1m = int(
            datetime.fromisoformat(
                datasets["trade_1m"]["end_time_utc"].replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
        latest_4h = int(
            datetime.fromisoformat(
                datasets["trade_4h"]["end_time_utc"].replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
        latest_1d = int(
            datetime.fromisoformat(
                datasets["trade_1d"]["end_time_utc"].replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
        lag_minutes = max(0, (boundaries["1m"]["open_time_utc_ms"] - latest_1m) // ONE_MINUTE_MS)
        lag_4h = max(0, (boundaries["4h"]["open_time_utc_ms"] - latest_4h) // FOUR_HOURS_MS)
        lag_days = max(0, (boundaries["1d"]["open_time_utc_ms"] - latest_1d) // ONE_DAY_MS)
        per_symbol[symbol] = {
            "data_lag_minutes": lag_minutes,
            "data_lag_4h_bars": lag_4h,
            "data_lag_days": lag_days,
            "status": classify_freshness(data_lag_minutes=lag_minutes, data_lag_4h_bars=lag_4h),
        }
    return {
        "source_server_time_utc_ms": server_time,
        "source_server_time_utc": utc_text(server_time),
        "latest_fully_closed": {
            name: {
                **value,
                "open_time_utc": utc_text(value["open_time_utc_ms"]),
                "close_time_utc": utc_text(value["close_time_utc_ms"]),
            }
            for name, value in boundaries.items()
        },
        "symbols": per_symbol,
        "overall_status": max(
            (item["status"] for item in per_symbol.values()),
            key=lambda value: {"FRESH": 0, "STALE": 1, "SEVERELY_STALE": 2}[value],
        ),
    }


def _download_delta_dataset(
    *,
    client: BinancePublicClient,
    store: AtomicDatasetStore,
    symbol: str,
    spec: Mapping[str, Any],
    start: int,
    end: int,
    server_time: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    downloader = DatasetDownloader(client, store, clock_ms=lambda: int(time.time() * 1_000))
    if spec["stream"] == "funding":
        records, manifest = _download_funding(
            downloader=downloader,
            store=store,
            symbol=symbol,
            start_time_ms=start,
            end_time_ms=end,
            page_limit=1000,
            existing_data_policy="reject",
        )
    else:
        records, manifest = _download_klines(
            downloader=downloader,
            store=store,
            symbol=symbol,
            interval=spec["interval"],
            stream=spec["stream"],
            start_time_ms=start,
            end_time_ms=end,
            page_limit=1000,
            source_server_time_utc_ms=server_time,
            existing_data_policy="reject",
        )
    return [asdict(record) for record in records], manifest


def refresh_snapshot(
    *,
    client: BinancePublicClient,
    old_root: Path,
    output_root: Path,
    server_time: int,
) -> tuple[Path, dict[str, Any]]:
    version = datetime.fromtimestamp(server_time / 1_000, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    root = output_root / "refreshed" / version
    if root.exists():
        raise FileExistsError(f"Versioned refresh directory already exists: {root}")
    store = AtomicDatasetStore(root)
    boundaries = latest_closed_boundaries(server_time)
    manifests: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    additions: dict[str, int] = {}
    overlap_duplicates: dict[str, int] = {}
    old_hashes: dict[str, str] = {}
    for symbol in SYMBOLS:
        for spec in dataset_specs(symbol):
            name = spec["name"]
            old = read_jsonl(old_root / "canonical" / f"{name}.jsonl")
            key = spec["key"]
            old_manifest = read_json(old_root / "manifests" / f"{name}.json")
            old_hashes[name] = old_manifest["dataset_content_hash"]
            last = max(int(record[key]) for record in old)
            start = last + (spec["step"] or 1)
            end = server_time
            if spec["interval"]:
                end = boundaries[spec["interval"]]["close_time_utc_ms"]
            new, delta_manifest = _download_delta_dataset(
                client=client,
                store=store,
                symbol=symbol,
                spec=spec,
                start=start,
                end=end,
                server_time=server_time,
            )
            merged, duplicates = merge_records(old, new, key_field=key)
            merged_list = [dict(record) for record in merged]
            content_hash = dataset_content_hash(merged_list, key_fields=("symbol", key))
            store.write_canonical_jsonl(
                f"canonical/{name}.jsonl", merged_list, key_fields=("symbol", key)
            )
            manifest = {
                "dataset_name": name,
                "canonical_schema_version": merged_list[0]["schema_version"],
                "old_dataset_content_hash": old_manifest["dataset_content_hash"],
                "dataset_content_hash": content_hash,
                "old_record_count": len(old),
                "new_record_count": len(new),
                "record_count": len(merged_list),
                "overlap_duplicate_count": duplicates,
                "start_time_utc_ms": int(merged_list[0][key]),
                "end_time_utc_ms": int(merged_list[-1][key]),
                "delta_acquisition": delta_manifest,
            }
            manifest["acquisition_manifest_hash"] = acquisition_manifest_hash(manifest)
            store.write_json_atomic(f"manifests/{name}.json", manifest)
            manifests[name] = manifest
            hashes[name] = content_hash
            additions[name] = len(new)
            overlap_duplicates[name] = duplicates

    exchange = client.get_json("/fapi/v1/exchangeInfo", {})
    if not isinstance(exchange, dict):
        raise TypeError("exchangeInfo must return an object")
    source_hash = hashlib.sha256(canonical_dumps(exchange).encode()).hexdigest()
    rules = normalize_contract_rules(
        exchange, symbols=SYMBOLS, acquired_at_utc_ms=server_time, source_hash=source_hash
    )
    rule_dicts = [asdict(rule) for rule in rules]
    rule_hash = dataset_content_hash(rule_dicts, key_fields=("symbol",))
    store.write_canonical_jsonl(
        "canonical/contract_rules_current.jsonl", rule_dicts, key_fields=("symbol",)
    )
    rule_manifest = {
        "dataset_name": "contract_rules_current",
        "canonical_schema_version": CONTRACT_RULE_SCHEMA_VERSION,
        "dataset_content_hash": rule_hash,
        "record_count": len(rule_dicts),
        "acquired_at_utc_ms": server_time,
        "source_hash": source_hash,
        "validity": "CURRENT_SNAPSHOT_ONLY",
    }
    rule_manifest["acquisition_manifest_hash"] = acquisition_manifest_hash(rule_manifest)
    store.write_json_atomic("manifests/contract_rules_current.json", rule_manifest)
    hashes["contract_rules_current"] = rule_hash
    bundle_hash = versioned_content_bundle_hash(
        bundle_version=ACQUISITION_BUNDLE_CONTENT_VERSION, dataset_hashes=hashes
    )
    acquisition = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "source": PUBLIC_BASE_URL,
        "public_get_only": True,
        "source_server_time_utc_ms": server_time,
        "old_snapshot_root": str(old_root.resolve()),
        "old_dataset_content_hashes": old_hashes,
        "new_dataset_content_hashes": hashes,
        "dataset_content_hash": bundle_hash,
        "new_record_counts": additions,
        "overlap_duplicate_counts": overlap_duplicates,
        "dataset_manifests": manifests,
        "contract_rule_manifest": rule_manifest,
    }
    acquisition["acquisition_manifest_hash"] = acquisition_manifest_hash(acquisition)
    acquisition["acquisition_run_id"] = acquisition_run_id(acquisition)
    store.write_json_atomic("acquisition_manifest.json", acquisition)
    store.write_json_atomic("summary.json", acquisition)
    return root, acquisition


def gap_report(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for symbol in SYMBOLS:
        result[symbol] = {}
        for spec in dataset_specs(symbol):
            records = read_jsonl(root / "canonical" / f"{spec['name']}.jsonl")
            key = spec["key"]
            times = [int(record[key]) for record in records]
            if spec["stream"] == "funding":
                report = detect_funding_gap_intervals(
                    times,
                    expected_start_ms=times[0],
                    expected_end_ms=times[-1],
                    schedule_version=FUNDING_SCHEDULE_VERSION,
                )
            else:
                report = detect_gap_intervals(
                    stream=spec["name"],
                    timestamps=times,
                    expected_step_ms=spec["step"],
                    expected_start_ms=times[0],
                    expected_end_ms=times[-1],
                )
            item = asdict(report)
            item["gap_count"] = len(item["intervals"])
            for interval in item["intervals"]:
                interval["start_time_utc"] = utc_text(interval["start_utc_ms"])
                interval["end_time_utc"] = utc_text(interval["end_utc_ms"])
            result[symbol][spec["name"].removeprefix(f"{symbol}_")] = item
    return result


def _remote_normalized(
    client: BinancePublicClient, symbol: str, kind: str, local: Mapping[str, Any]
) -> dict[str, Any] | None:
    if kind == "funding":
        timestamp = int(local["funding_time_utc_ms"])
        payload = client.get_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": timestamp, "endTime": timestamp, "limit": 1},
        )
        if not isinstance(payload, list) or not payload:
            return None
        item = payload[0]
        return {
            "funding_time_utc_ms": int(item["fundingTime"]),
            "funding_rate": str(item["fundingRate"]),
            "mark_price": str(item["markPrice"]),
        }
    interval = "1m" if kind in {"trade_1m", "mark_1m"} else kind.removeprefix("trade_")
    path = "/fapi/v1/markPriceKlines" if kind == "mark_1m" else "/fapi/v1/klines"
    timestamp = int(local["open_time_utc_ms"])
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": timestamp,
        "endTime": int(local["close_time_utc_ms"]),
        "limit": 1,
    }
    payload = client.get_json(path, params)
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    common = {
        "open_time_utc_ms": int(row[0]),
        "open": str(row[1]),
        "high": str(row[2]),
        "low": str(row[3]),
        "close": str(row[4]),
        "close_time_utc_ms": int(row[6]),
    }
    if kind != "mark_1m":
        common.update(
            {
                "base_volume": str(row[5]),
                "quote_volume": str(row[7]),
                "trade_count": int(row[8]),
                "taker_buy_base_volume": str(row[9]),
                "taker_buy_quote_volume": str(row[10]),
            }
        )
    return common


def fields_equal(field: str, local: Any, remote: Any) -> bool:
    if field.endswith("_utc_ms") or field == "trade_count":
        return int(local) == int(remote)
    try:
        return Decimal(str(local)) == Decimal(str(remote))
    except Exception:
        return local == remote


def reconcile_samples(client: BinancePublicClient, root: Path) -> dict[str, Any]:
    counts = {"trade_1m": 30, "mark_1m": 20, "trade_4h": 10, "trade_1d": 10, "funding": 10}
    output: dict[str, Any] = {
        "sample_seed": SAMPLE_SEED,
        "sample_rule_version": SAMPLE_RULE_VERSION,
        "sample_rule": "Rank SHA256(seed|namespace|timestamp) ascending; take N; report in timestamp order",
        "symbols": {},
        "totals": {
            "matched": 0,
            "mismatched": 0,
            "missing_from_remote": 0,
            "missing_from_local": 0,
        },
    }
    for symbol in SYMBOLS:
        output["symbols"][symbol] = {}
        for kind, count in counts.items():
            records = read_jsonl(root / "canonical" / f"{symbol}_{kind}.jsonl")
            key = "funding_time_utc_ms" if kind == "funding" else "open_time_utc_ms"
            selected = deterministic_sample(
                records,
                count=count,
                seed=SAMPLE_SEED,
                namespace=f"{symbol}|{kind}",
                timestamp_field=key,
            )
            summary = {
                "requested": count,
                "matched": 0,
                "mismatched": 0,
                "missing_from_remote": 0,
                "missing_from_local": 0,
                "details": [],
            }
            for local in selected:
                remote = _remote_normalized(client, symbol, kind, local)
                timestamp = int(local[key])
                if remote is None:
                    summary["missing_from_remote"] += 1
                    summary["details"].append(
                        {"time_utc": utc_text(timestamp), "status": "MISSING_FROM_REMOTE"}
                    )
                    continue
                fields = tuple(remote)
                differences = [
                    {"field": field, "local": str(local.get(field)), "remote": str(remote[field])}
                    for field in fields
                    if not fields_equal(field, local.get(field), remote[field])
                ]
                if differences:
                    summary["mismatched"] += 1
                    summary["details"].append(
                        {
                            "time_utc": utc_text(timestamp),
                            "status": "MISMATCHED",
                            "fields": differences,
                        }
                    )
                else:
                    summary["matched"] += 1
                    summary["details"].append(
                        {"time_utc": utc_text(timestamp), "status": "MATCHED"}
                    )
            output["symbols"][symbol][kind] = summary
            for metric in output["totals"]:
                output["totals"][metric] += summary[metric]
    return output


def coverage_report(root: Path) -> dict[str, Any]:
    per_symbol: dict[str, Any] = {}
    common_starts: list[int] = []
    common_ends: list[int] = []
    for symbol in SYMBOLS:
        trade = read_jsonl(root / "canonical" / f"{symbol}_trade_1m.jsonl")
        mark = read_jsonl(root / "canonical" / f"{symbol}_mark_1m.jsonl")
        funding = read_jsonl(root / "canonical" / f"{symbol}_funding.jsonl")
        start = max(
            int(trade[0]["open_time_utc_ms"]),
            int(mark[0]["open_time_utc_ms"]),
            int(funding[0]["funding_time_utc_ms"]),
        )
        end = min(
            int(trade[-1]["close_time_utc_ms"]),
            int(mark[-1]["close_time_utc_ms"]),
            int(funding[-1]["funding_time_utc_ms"]),
        )
        common_starts.append(start)
        common_ends.append(end)
        per_symbol[symbol] = {"common_start_utc": utc_text(start), "common_end_utc": utc_text(end)}
    common_start = max(common_starts)
    common_end = min(common_ends)
    metrics = coverage_day_metrics(common_start, common_end)
    duration_days = Decimal(metrics["joint_common_duration_days"])
    return {
        "required": {
            "training_months": 36,
            "validation_months": 12,
            "oos_months": 18,
            "total_months": 66,
        },
        "symbols": per_symbol,
        "joint_common_start_utc": utc_text(common_start),
        "joint_common_end_utc": utc_text(common_end),
        "joint_common_duration_days": metrics["joint_common_duration_days"],
        "required_approximate_days": metrics["required_approximate_days"],
        "coverage_status": "SUFFICIENT" if metrics["sufficient"] else "DATA_COVERAGE_INSUFFICIENT",
        "longest_available_use": "FORMAL_66_MONTH" if metrics["sufficient"] else "DIAGNOSTIC_ONLY",
        "pre_roll": {
            "daily_250_bars_available": duration_days >= 250,
            "four_hour_100_bars_available": duration_days * 6 >= 100,
        },
        "contract_rule_coverage": "APPROXIMATED_CURRENT_SNAPSHOT_ONLY",
        "maintenance_evidence_coverage": "ABSENT",
    }


def write_reports(
    *,
    output: Path,
    connectivity: dict[str, Any],
    local: dict[str, Any],
    freshness: dict[str, Any],
    gaps: dict[str, Any],
    reconciliation: dict[str, Any],
    refreshed_manifest: dict[str, Any],
    coverage: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> str:
    output.mkdir(parents=True, exist_ok=True)
    store = AtomicDatasetStore(output)
    integrity_failed = (
        reconciliation["totals"]["mismatched"] > 0
        or reconciliation["totals"]["missing_from_remote"] > 0
        or any(
            dataset["duplicate_record_count"] or dataset["unclosed_kline_count"]
            for symbol in local["symbols"].values()
            for dataset in symbol.values()
        )
    )
    if integrity_failed:
        status = "DATA_INTEGRITY_FAILED"
    elif coverage["coverage_status"] != "SUFFICIENT":
        status = "DATA_COVERAGE_INSUFFICIENT"
    elif freshness["overall_status"] != "FRESH":
        status = "STALE_DATA_REFRESH_REQUIRED"
    else:
        status = "READY_FOR_BASELINE_EVALUATION"
    assert status in FINAL_STATUSES
    report = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "final_status": status,
        "two_d_authorized": status == "READY_FOR_BASELINE_EVALUATION",
        "source_policy": {
            "base_url": PUBLIC_BASE_URL,
            "public_get_only": True,
            "api_key_used": False,
            "third_party_source_used": False,
            "synthetic_data_used": False,
        },
        "discovered_snapshots": snapshots,
        "local_coverage": local,
        "freshness": freshness,
        "sample_reconciliation": reconciliation,
        "gap_report": gaps,
        "coverage_requirements": coverage,
        "refreshed_dataset_manifest": refreshed_manifest,
        "next_update_design": {
            "implementation_status": "DESIGN_ONLY_NOT_IMPLEMENTED",
            "schedule": "After each UTC 4H close, wait one minute, query /fapi/v1/time, then incrementally GET only fully closed trade/mark/index klines and funding data",
            "closed_bar_rule": "Reject any kline with close_time >= Binance serverTime",
            "retries": "Bounded exponential retry for 429, 5xx, and network errors; preserve checkpoint and fail closed on unresolved gaps",
            "decision_flow": "Validate canonical data and gaps, then invoke existing deterministic Candidate and ExecutionPlan stages without account connectivity",
            "forbidden": [
                "WebSocket",
                "API Key",
                "account endpoint",
                "create_order",
                "automatic order",
                "long-running service",
            ],
        },
    }
    for name, value in (
        ("data_readiness_report.json", report),
        ("endpoint_connectivity.json", connectivity),
        ("local_coverage.json", local),
        ("freshness.json", freshness),
        ("sample_reconciliation.json", reconciliation),
        ("gap_report.json", gaps),
        ("refreshed_dataset_manifest.json", refreshed_manifest),
    ):
        store.write_json_atomic(name, value)
    lines = [
        "# Binance USD-M 数据就绪审计",
        "",
        f"最终状态: `{status}`",
        "",
        f"2D 是否获准: `{str(status == 'READY_FOR_BASELINE_EVALUATION').lower()}`",
        "",
        "## 数据来源",
        "",
        f"仅使用 `{PUBLIC_BASE_URL}` 的六个 allowlisted 公共 GET 端点; 未使用 API Key、账户、订单、第三方或合成数据。",
        "",
        "## 当前共同覆盖",
        "",
        f"- BTC/ETH、trade/mark/funding 共同起点: {coverage['joint_common_start_utc']}",
        f"- 共同终点: {coverage['joint_common_end_utc']}",
        f"- 共同覆盖: {Decimal(coverage['joint_common_duration_days']):.6f} 天, 要求约 {Decimal(coverage['required_approximate_days']):.6f} 天 (66个月)",
        "- 可用性质: `" + coverage["longest_available_use"] + "`",
        "",
        "## 在线真实性抽样",
        "",
        f"固定 seed `{SAMPLE_SEED}`, 规则 `{SAMPLE_RULE_VERSION}`。",
        "",
        f"matched={reconciliation['totals']['matched']}, mismatched={reconciliation['totals']['mismatched']}, missing_from_remote={reconciliation['totals']['missing_from_remote']}, missing_from_local={reconciliation['totals']['missing_from_local']}",
        "",
        "## 后续最小更新方案 (仅设计, 未实现)",
        "",
        "每个 UTC 4H 收盘后等待一分钟, 以 Binance serverTime 为唯一闭合判据进行公共 REST 增量刷新; 分页断点恢复、限次重试, 关键流缺口 fail closed。校验通过后才调用现有确定性 Candidate/ExecutionPlan; 不需要 API Key, 不连接账户, 不实现 WebSocket、自动下单或长期后台服务。",
        "",
        "## 结论",
        "",
        "当前数据覆盖不足 66 个月, 因此仅可用于 `DIAGNOSTIC_ONLY`, 不得称为正式 OOS, 也不得继续 2D。"
        if status == "DATA_COVERAGE_INSUFFICIENT"
        else f"状态为 `{status}`。",
        "",
    ]
    (output / "data_readiness_report.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    return status


def run_audit(search_root: Path, output: Path) -> str:
    client = BinancePublicClient()
    time_payload = client.get_json("/fapi/v1/time", {})
    if not isinstance(time_payload, dict) or not isinstance(time_payload.get("serverTime"), int):
        raise ValueError("Invalid Binance serverTime response")
    server_time = int(time_payload["serverTime"])
    selected, snapshots = discover_snapshots(search_root)
    old_local = inventory_snapshot(selected, server_time)
    old_freshness = freshness_report(old_local, server_time)
    connectivity = connectivity_check(client, server_time)
    refreshed_manifest: dict[str, Any] = {"refresh_performed": False}
    active_root = selected
    if old_freshness["overall_status"] != "FRESH":
        reusable = sorted((output / "refreshed").glob("*/summary.json"))
        if reusable:
            candidate = reusable[-1].parent
            candidate_local = inventory_snapshot(candidate, server_time)
            if freshness_report(candidate_local, server_time)["overall_status"] == "FRESH":
                active_root = candidate
                refreshed_manifest = read_json(candidate / "acquisition_manifest.json")
                refreshed_manifest = {
                    "refresh_performed": True,
                    "reused_completed_refresh": True,
                    "refreshed_root": str(active_root.resolve()),
                    **refreshed_manifest,
                }
        if active_root == selected:
            active_root, refreshed_manifest = refresh_snapshot(
                client=client,
                old_root=selected,
                output_root=output,
                server_time=server_time,
            )
            refreshed_manifest = {
                "refresh_performed": True,
                "reused_completed_refresh": False,
                "refreshed_root": str(active_root.resolve()),
                **refreshed_manifest,
            }
    local = inventory_snapshot(active_root, server_time)
    freshness = freshness_report(local, server_time)
    gaps = gap_report(active_root)
    reconciliation = reconcile_samples(client, active_root)
    coverage = coverage_report(active_root)
    return write_reports(
        output=output,
        connectivity=connectivity,
        local=local,
        freshness=freshness,
        gaps=gaps,
        reconciliation=reconciliation,
        refreshed_manifest=refreshed_manifest,
        coverage=coverage,
        snapshots=snapshots,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Binance USD-M public research data readiness"
    )
    parser.add_argument("--search-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        status = run_audit(args.search_root, args.output)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        status = (
            "SOURCE_UNAVAILABLE"
            if exc.__class__.__name__ in {"PublicTransportError", "URLError"}
            else "DATA_INTEGRITY_FAILED"
        )
        AtomicDatasetStore(args.output).write_json_atomic(
            "data_readiness_report.json",
            {
                "audit_schema_version": AUDIT_SCHEMA_VERSION,
                "final_status": status,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "two_d_authorized": False,
            },
        )
        raise
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
