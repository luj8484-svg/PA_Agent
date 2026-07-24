from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import os
import re
import shutil
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from pa_agent.research_data.binance_public import BinancePublicClient
from pa_agent.research_data.canonical import canonical_dumps
from pa_agent.research_data.downloader import PublicGetRetrier
from pa_agent.research_data.hashing import versioned_content_bundle_hash
from pa_agent.research_data.historical_archive import (
    ARCHIVE_BASE_URL,
    S3_LIST_URL,
    ArchiveObject,
    build_experiment_split_candidate,
    canonicalize_csv_rows,
    estimate_resources,
    fields_equal,
    parse_checksum,
    parse_s3_listing,
    validate_archive_url,
)
from pa_agent.research_data.normalize import normalize_price_kline
from pa_agent.research_data.storage import AtomicDatasetStore
from pa_agent.research_data.validation import (
    ABSOLUTE_TOLERANCES,
    AGGREGATION_VALIDATION_VERSION,
    RELATIVE_TOLERANCE,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT")
STREAMS = (
    ("trade_1m", "klines", "trade", "1m", 60_000),
    ("mark_1m", "markPriceKlines", "mark", "1m", 60_000),
    ("index_1m", "indexPriceKlines", "index", "1m", 60_000),
    ("trade_4h", "klines", "trade", "4h", 14_400_000),
    ("trade_1d", "klines", "trade", "1d", 86_400_000),
    ("funding", "fundingRate", "funding", None, None),
)
SAMPLE_SEED = 20260719
SAMPLE_ALGORITHM = "SHA256_LOWEST_BY_SEED_SYMBOL_STREAM_YEAR_TIMESTAMP_V1"


def retry_transient(operation, *, max_attempts: int = 5, sleep=time.sleep):
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return operation()
        except HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt + 1 == max_attempts:
                raise
        except (RemoteDisconnected, URLError, TimeoutError, OSError):
            if attempt + 1 == max_attempts:
                raise
        sleep(min(8.0, 0.5 * (2**attempt)))
    raise AssertionError("unreachable")


def utc_text(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000, tz=UTC).isoformat().replace("+00:00", "Z")


def get_bytes(url: str, *, timeout: float = 90.0) -> bytes:
    def operation() -> bytes:
        request = Request(url, method="GET", headers={"User-Agent": "PA-Agent-Research/1.0"})
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    return retry_transient(operation)


def list_objects(prefix: str) -> tuple[ArchiveObject, ...]:
    marker: str | None = None
    result: list[ArchiveObject] = []
    while True:
        params: dict[str, Any] = {"prefix": prefix, "max-keys": 1000}
        if marker:
            params["marker"] = marker
        payload = get_bytes(f"{S3_LIST_URL}?{urlencode(params)}")
        objects, marker = parse_s3_listing(payload)
        result.extend(objects)
        if marker is None:
            return tuple(result)


def archive_prefix(symbol: str, kind: str, interval: str | None) -> str:
    suffix = f"{interval}/" if interval else ""
    return f"data/futures/um/monthly/{kind}/{symbol}/{suffix}"


def month_from_key(key: str) -> str:
    match = re.search(r"(\d{4}-\d{2})\.zip$", key)
    if not match:
        raise ValueError(f"Archive key has no month: {key}")
    return match.group(1)


def discover() -> tuple[dict[str, Any], list[tuple[str, str, str, str | None, ArchiveObject]]]:
    inventory: dict[str, Any] = {
        "source": ARCHIVE_BASE_URL,
        "source_type": "BINANCE_OFFICIAL_PUBLIC_ARCHIVE",
        "symbols": {},
    }
    selected: list[tuple[str, str, str, str | None, ArchiveObject]] = []
    for symbol in SYMBOLS:
        inventory["symbols"][symbol] = {}
        for name, kind, stream, interval, _step in STREAMS:
            objects = list_objects(archive_prefix(symbol, kind, interval))
            zips = tuple(item for item in objects if item.key.endswith(".zip"))
            checksums = {
                item.key.removesuffix(".CHECKSUM")
                for item in objects
                if item.key.endswith(".zip.CHECKSUM")
            }
            if not zips or any(item.key not in checksums for item in zips):
                raise ValueError(f"ARCHIVE_LISTING_INCOMPLETE: {symbol} {name}")
            months = [month_from_key(item.key) for item in zips]
            inventory["symbols"][symbol][name] = {
                "prefix": archive_prefix(symbol, kind, interval),
                "earliest_month": min(months),
                "latest_month": max(months),
                "month_count": len(months),
                "compressed_bytes": sum(item.size_bytes for item in zips),
                "all_months_have_checksum": True,
            }
            selected.extend((symbol, name, stream, interval, item) for item in zips)
    return inventory, selected


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_download(url: str, target: Path, expected_sha256: str) -> tuple[bool, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        actual = _sha256_file(target)
        if actual != expected_sha256:
            raise ValueError(f"IMMUTABLE_RAW_CONFLICT: {target}")
        return True, target.stat().st_size
    temporary = target.with_suffix(target.suffix + ".part")
    if temporary.exists():
        temporary.unlink()

    def operation() -> None:
        temporary.unlink(missing_ok=True)
        request = Request(url, method="GET", headers={"User-Agent": "PA-Agent-Research/1.0"})
        digest = hashlib.sha256()
        with urlopen(request, timeout=180) as response, temporary.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if digest.hexdigest() != expected_sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"RAW_CHECKSUM_MISMATCH: {url}")

    retry_transient(operation)
    os.replace(temporary, target)
    return False, target.stat().st_size


def canonicalize_zip(
    *, raw_path: Path, canonical_path: Path, symbol: str, stream: str, interval: str | None
) -> dict[str, Any]:
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    if canonical_path.exists():
        count = 0
        first_time = last_time = previous = None
        duplicates = 0
        key = "funding_time_utc_ms" if stream == "funding" else "open_time_utc_ms"
        with canonical_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                timestamp = int(json.loads(line)[key])
                if previous == timestamp:
                    duplicates += 1
                first_time = timestamp if first_time is None else first_time
                last_time = timestamp
                previous = timestamp
                count += 1
        return {
            "canonical_path": str(canonical_path.resolve()),
            "canonical_bytes": canonical_path.stat().st_size,
            "canonical_content_hash": _sha256_file(canonical_path),
            "record_count": count,
            "first_time_utc_ms": first_time,
            "last_time_utc_ms": last_time,
            "duplicate_count": duplicates,
            "reused_canonical": True,
        }
    temporary = canonical_path.with_suffix(".jsonl.part")
    count = 0
    first_time: int | None = None
    last_time: int | None = None
    previous: int | None = None
    duplicates = 0
    digest = hashlib.sha256()
    with ZipFile(raw_path) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError(f"INVALID_ARCHIVE_ZIP_LAYOUT: {raw_path}")
        with archive.open(names[0]) as binary, temporary.open("wb") as output:
            text = (line.decode("utf-8").rstrip("\r\n") for line in binary)
            reader = csv.reader(text)
            for row in reader:
                records = canonicalize_csv_rows(
                    [row], symbol=symbol, stream=stream, interval=interval
                )
                if not records:
                    continue
                record = records[0]
                key = "funding_time_utc_ms" if stream == "funding" else "open_time_utc_ms"
                timestamp = int(record[key])
                if previous is not None:
                    if timestamp < previous:
                        raise ValueError(f"TIMESTAMP_NOT_SORTED: {raw_path}")
                    if timestamp == previous:
                        duplicates += 1
                previous = timestamp
                first_time = timestamp if first_time is None else first_time
                last_time = timestamp
                encoded = (canonical_dumps(record) + "\n").encode()
                output.write(encoded)
                digest.update(encoded)
                count += 1
            output.flush()
            os.fsync(output.fileno())
    os.replace(temporary, canonical_path)
    return {
        "canonical_path": str(canonical_path.resolve()),
        "canonical_bytes": canonical_path.stat().st_size,
        "canonical_content_hash": digest.hexdigest(),
        "record_count": count,
        "first_time_utc_ms": first_time,
        "last_time_utc_ms": last_time,
        "duplicate_count": duplicates,
        "reused_canonical": False,
    }


def acquire_one(
    output: Path, entry: tuple[str, str, str, str | None, ArchiveObject]
) -> dict[str, Any]:
    symbol, name, stream, interval, obj = entry
    month = month_from_key(obj.key)
    filename = Path(obj.key).name
    url = validate_archive_url(f"{ARCHIVE_BASE_URL}/{obj.key}")
    checksum_text = get_bytes(url + ".CHECKSUM").decode("utf-8")
    expected = parse_checksum(checksum_text, filename)
    raw_path = output / "data" / "raw" / symbol / name / filename
    canonical_path = output / "data" / "canonical" / symbol / name / f"{month}.jsonl"
    manifest_path = output / "data" / "manifests" / symbol / name / f"{month}.json"
    if manifest_path.exists() and raw_path.exists() and canonical_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("expected_sha256") != expected:
            raise ValueError(f"OFFICIAL_CHECKSUM_CHANGED: {url}")
        if _sha256_file(raw_path) != existing.get("raw_sha256"):
            raise ValueError(f"IMMUTABLE_RAW_CONFLICT: {raw_path}")
        if _sha256_file(canonical_path) != existing.get("canonical_content_hash"):
            raise ValueError(f"IMMUTABLE_CANONICAL_CONFLICT: {canonical_path}")
        existing["reused_raw"] = True
        existing["reused_canonical"] = True
        return existing
    reused_raw, raw_bytes = _atomic_download(url, raw_path, expected)
    canonical = canonicalize_zip(
        raw_path=raw_path,
        canonical_path=canonical_path,
        symbol=symbol,
        stream=stream,
        interval=interval,
    )
    manifest = {
        "symbol": symbol,
        "stream_name": name,
        "month": month,
        "official_filename": filename,
        "source_url": url,
        "official_checksum_url": url + ".CHECKSUM",
        "expected_sha256": expected,
        "raw_sha256": _sha256_file(raw_path),
        "raw_bytes": raw_bytes,
        "reused_raw": reused_raw,
        **canonical,
    }
    manifest["manifest_hash"] = hashlib.sha256(canonical_dumps(manifest).encode()).hexdigest()
    AtomicDatasetStore(output).write_json_atomic(manifest_path.relative_to(output), manifest)
    return manifest


def merge_record_sequences(
    archive_records, patch_records, *, key: str
) -> tuple[dict[str, Any], ...]:
    merged: dict[int, dict[str, Any]] = {}
    encoded: dict[int, str] = {}
    for record in (*archive_records, *patch_records):
        timestamp = int(record[key])
        canonical = canonical_dumps(record)
        if timestamp in merged:
            if encoded[timestamp] != canonical:
                raise ValueError(f"CONFLICTING_DUPLICATE: {key}={timestamp}")
            continue
        merged[timestamp] = record
        encoded[timestamp] = canonical
    return tuple(merged[timestamp] for timestamp in sorted(merged))


def iter_records(output: Path, symbol: str, name: str):
    folder = output / "data" / "canonical" / symbol / name
    for path in sorted(folder.glob("*.jsonl")):
        archive_records: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    archive_records.append(json.loads(line))
        patch_path = output / "data" / "rest_gap_fill" / "canonical" / symbol / name / path.name
        patch_records: list[dict[str, Any]] = []
        if patch_path.exists():
            with patch_path.open(encoding="utf-8") as handle:
                patch_records = [json.loads(line) for line in handle if line.strip()]
        key = "funding_time_utc_ms" if name == "funding" else "open_time_utc_ms"
        yield from merge_record_sequences(archive_records, patch_records, key=key)


def validate_streams(
    output: Path, manifests: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    report: dict[str, Any] = {}
    coverage: dict[str, Any] = {}
    by_stream: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in manifests:
        by_stream[item["symbol"], item["stream_name"]].append(item)
    for symbol in SYMBOLS:
        report[symbol] = {}
        coverage[symbol] = {}
        for name, _kind, stream, _interval, step in STREAMS:
            count = 0
            first = last = previous = None
            gaps: list[dict[str, Any]] = []
            duplicates = 0
            unclosed = 0
            for record in iter_records(output, symbol, name):
                key = "funding_time_utc_ms" if stream == "funding" else "open_time_utc_ms"
                timestamp = int(record[key])
                if previous is not None:
                    if timestamp == previous:
                        duplicates += 1
                    elif stream != "funding" and timestamp != previous + int(step):
                        gaps.append(
                            {
                                "start_utc": utc_text(previous + int(step)),
                                "end_utc": utc_text(timestamp - 1),
                            }
                        )
                    elif stream == "funding" and timestamp - previous > 28_801_000:
                        gaps.append(
                            {
                                "start_utc": utc_text(previous + 28_800_000),
                                "end_utc": utc_text(timestamp - 1),
                            }
                        )
                if stream != "funding" and not record.get("is_closed", False):
                    unclosed += 1
                first = timestamp if first is None else first
                last = timestamp
                previous = timestamp
                count += 1
            report[symbol][name] = {
                "record_count": count,
                "duplicate_count": duplicates,
                "conflicting_duplicate_count": 0,
                "gap_count": len(gaps),
                "gap_intervals": gaps,
                "unclosed_kline_count": unclosed,
                "month_shard_count": len(by_stream[symbol, name]),
                "all_raw_checksums_match": all(
                    x["expected_sha256"] == x["raw_sha256"] for x in by_stream[symbol, name]
                ),
                "all_manifest_hashes_present": all(
                    bool(x["manifest_hash"]) for x in by_stream[symbol, name]
                ),
            }
            coverage[symbol][name] = {
                "earliest_time_utc": utc_text(first),
                "latest_time_utc": utc_text(last),
                "record_count": count,
            }
    return report, coverage


def _iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def fill_price_gaps(output: Path, gaps: dict[str, Any]) -> dict[str, Any]:
    client = BinancePublicClient()
    requester = PublicGetRetrier(client, max_retries=5, base_delay_seconds=0.5)
    by_file: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    evidence: list[dict[str, Any]] = []
    store = AtomicDatasetStore(output)
    for symbol in SYMBOLS:
        for name in ("mark_1m", "index_1m"):
            path = "/fapi/v1/markPriceKlines" if name == "mark_1m" else "/fapi/v1/indexPriceKlines"
            stream = "mark" if name == "mark_1m" else "index"
            identity = "symbol" if name == "mark_1m" else "pair"
            for gap_index, gap in enumerate(gaps[symbol][name]["gap_intervals"]):
                start = _iso_ms(gap["start_utc"])
                end = _iso_ms(gap["end_utc"])
                current = start
                pages: list[dict[str, Any]] = []
                records: list[dict[str, Any]] = []
                page_index = 0
                while current <= end:
                    params = {
                        identity: symbol,
                        "interval": "1m",
                        "startTime": current,
                        "endTime": end,
                        "limit": 1500,
                    }
                    payload, retry_count = requester.get_json(path, params)
                    if not isinstance(payload, list):
                        raise TypeError("Gap-fill endpoint must return an array")
                    raw_name = f"data/rest_gap_fill/raw/{symbol}/{name}/gap-{gap_index:03d}-page-{page_index:03d}.json"
                    store.write_json_atomic(
                        raw_name,
                        {
                            "path": path,
                            "params": params,
                            "retry_count": retry_count,
                            "payload": payload,
                        },
                    )
                    pages.append(
                        {"path": raw_name, "row_count": len(payload), "retry_count": retry_count}
                    )
                    if not payload:
                        break
                    for row in payload:
                        model = normalize_price_kline(
                            row,
                            stream=stream,
                            symbol=symbol,
                            interval="1m",
                            source_server_time_utc_ms=2**63 - 1,
                        )
                        item = {
                            key: str(value) if isinstance(value, Decimal) else value
                            for key, value in asdict(model).items()
                        }
                        records.append(item)
                        month = datetime.fromtimestamp(
                            item["open_time_utc_ms"] / 1000, tz=UTC
                        ).strftime("%Y-%m")
                        by_file[symbol, name, month].append(item)
                    last = int(payload[-1][0])
                    if last < current:
                        raise ValueError("REST_GAP_FILL_DID_NOT_ADVANCE")
                    current = last + 60_000
                    page_index += 1
                    if len(payload) < 1500:
                        break
                evidence.append(
                    {
                        "symbol": symbol,
                        "stream": name,
                        "gap_start_utc": gap["start_utc"],
                        "gap_end_utc": gap["end_utc"],
                        "record_count": len(records),
                        "pages": pages,
                    }
                )
    patch_hashes: dict[str, str] = {}
    for (symbol, name, month), records in sorted(by_file.items()):
        target = output / "data" / "rest_gap_fill" / "canonical" / symbol / name / f"{month}.jsonl"
        existing: list[dict[str, Any]] = []
        if target.exists():
            existing = [
                json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line
            ]
        merged = merge_record_sequences(existing, records, key="open_time_utc_ms")
        store.write_canonical_jsonl(
            target.relative_to(output), merged, key_fields=("symbol", "open_time_utc_ms")
        )
        patch_hashes[f"{symbol}|{name}|{month}"] = _sha256_file(target)
    result = {
        "source": "https://fapi.binance.com",
        "public_get_only": True,
        "gap_count_requested": len(evidence),
        "record_count": sum(item["record_count"] for item in evidence),
        "gaps": evidence,
        "patch_content_hashes": patch_hashes,
    }
    result["manifest_hash"] = hashlib.sha256(canonical_dumps(result).encode()).hexdigest()
    return result


def aggregate_trade_records(records, *, interval_ms: int) -> dict[int, dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    for record in records:
        timestamp = int(record["open_time_utc_ms"])
        bucket = timestamp // interval_ms * interval_ms
        current = buckets.get(bucket)
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
            buckets[bucket] = current
        current["high"] = str(max(Decimal(current["high"]), Decimal(str(record["high"]))))
        current["low"] = str(min(Decimal(current["low"]), Decimal(str(record["low"]))))
        current["close"] = str(record["close"])
        for field in (
            "base_volume",
            "quote_volume",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        ):
            current[field] = str(Decimal(current[field]) + Decimal(str(record[field])))
        current["trade_count"] += int(record["trade_count"])
        current["source_1m_count"] += 1
    return buckets


def _volume_equal(left: Any, right: Any, tolerance: Decimal) -> bool:
    left_decimal = Decimal(str(left))
    right_decimal = Decimal(str(right))
    difference = abs(left_decimal - right_decimal)
    if difference <= tolerance:
        return True
    denominator = max(abs(left_decimal), abs(right_decimal))
    return denominator != 0 and difference / denominator <= RELATIVE_TOLERANCE


def cross_validate_native(output: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "aggregation_validation_version": AGGREGATION_VALIDATION_VERSION,
        "symbols": {},
    }
    for symbol in SYMBOLS:
        result["symbols"][symbol] = {}
        for interval, interval_ms, native_name in (
            ("4h", 14_400_000, "trade_4h"),
            ("1d", 86_400_000, "trade_1d"),
        ):
            aggregated = aggregate_trade_records(
                iter_records(output, symbol, "trade_1m"), interval_ms=interval_ms
            )
            native = {
                int(record["open_time_utc_ms"]): record
                for record in iter_records(output, symbol, native_name)
            }
            issues: list[dict[str, Any]] = []
            issue_count = 0
            expected_count = interval_ms // 60_000
            for timestamp in sorted(set(aggregated) | set(native)):
                left = aggregated.get(timestamp)
                right = native.get(timestamp)
                field_issues: list[dict[str, Any]] = []
                if left is None or right is None:
                    field_issues.append(
                        {
                            "field": "bar_presence",
                            "aggregated": left is not None,
                            "native": right is not None,
                        }
                    )
                else:
                    if left["source_1m_count"] != expected_count:
                        field_issues.append(
                            {
                                "field": "source_1m_count",
                                "aggregated": left["source_1m_count"],
                                "native": expected_count,
                            }
                        )
                    for field in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "close_time_utc_ms",
                        "trade_count",
                    ):
                        if not fields_equal(field, left[field], right[field]):
                            field_issues.append(
                                {
                                    "field": field,
                                    "aggregated": str(left[field]),
                                    "native": str(right[field]),
                                }
                            )
                    for field, tolerance in ABSOLUTE_TOLERANCES.items():
                        if not _volume_equal(left[field], right[field], tolerance):
                            field_issues.append(
                                {
                                    "field": field,
                                    "aggregated": str(left[field]),
                                    "native": str(right[field]),
                                }
                            )
                if field_issues:
                    issue_count += len(field_issues)
                    if len(issues) < 100:
                        issues.append(
                            {"open_time_utc": utc_text(timestamp), "fields": field_issues}
                        )
            result["symbols"][symbol][interval] = {
                "valid": issue_count == 0,
                "compared_bars": len(set(aggregated) & set(native)),
                "issue_count": issue_count,
                "issue_samples": issues,
            }
    return result


def sample_records(
    output: Path, symbol: str, name: str, quota: int
) -> dict[int, list[dict[str, Any]]]:
    heaps: dict[int, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    stream = "funding" if name == "funding" else "kline"
    key = "funding_time_utc_ms" if stream == "funding" else "open_time_utc_ms"
    for record in iter_records(output, symbol, name):
        timestamp = int(record[key])
        year = datetime.fromtimestamp(timestamp / 1000, tz=UTC).year
        score = int(
            hashlib.sha256(
                f"{SAMPLE_SEED}|{symbol}|{name}|{year}|{timestamp}".encode()
            ).hexdigest(),
            16,
        )
        heap = heaps[year]
        item = (-score, timestamp, record)
        if len(heap) < quota:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return {
        year: [item[2] for item in sorted(heap, key=lambda x: x[1])]
        for year, heap in sorted(heaps.items())
    }


def remote_record(
    requester: PublicGetRetrier, symbol: str, name: str, local: dict[str, Any]
) -> dict[str, Any] | None:
    if name == "funding":
        timestamp = int(local["funding_time_utc_ms"])
        payload, _retry_count = requester.get_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": timestamp, "endTime": timestamp, "limit": 1},
        )
        if not isinstance(payload, list) or not payload:
            return None
        return {
            "funding_time_utc_ms": int(payload[0]["fundingTime"]),
            "funding_rate": payload[0]["fundingRate"],
        }
    interval = "1m" if name in {"trade_1m", "mark_1m"} else name.removeprefix("trade_")
    path = "/fapi/v1/markPriceKlines" if name == "mark_1m" else "/fapi/v1/klines"
    timestamp = int(local["open_time_utc_ms"])
    payload, _retry_count = requester.get_json(
        path,
        {
            "symbol": symbol,
            "interval": interval,
            "startTime": timestamp,
            "endTime": int(local["close_time_utc_ms"]),
            "limit": 1,
        },
    )
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    result = {
        "open_time_utc_ms": int(row[0]),
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "close_time_utc_ms": int(row[6]),
    }
    if name != "mark_1m":
        result.update(
            {
                "base_volume": row[5],
                "quote_volume": row[7],
                "trade_count": int(row[8]),
                "taker_buy_base_volume": row[9],
                "taker_buy_quote_volume": row[10],
            }
        )
    return result


def reconcile(output: Path) -> dict[str, Any]:
    client = BinancePublicClient()
    requester = PublicGetRetrier(client, max_retries=5, base_delay_seconds=0.5)
    quotas = {"trade_1m": 12, "mark_1m": 12, "trade_4h": 6, "trade_1d": 6, "funding": 6}
    result: dict[str, Any] = {
        "seed": SAMPLE_SEED,
        "algorithm": SAMPLE_ALGORITHM,
        "symbols": {},
        "totals": {
            "matched": 0,
            "mismatched": 0,
            "missing_from_remote": 0,
            "missing_from_local": 0,
        },
    }
    for symbol in SYMBOLS:
        result["symbols"][symbol] = {}
        for name, quota in quotas.items():
            years = sample_records(output, symbol, name, quota)
            stream_result: dict[str, Any] = {}
            for year, samples in years.items():
                stats = {
                    "matched": 0,
                    "mismatched": 0,
                    "missing_from_remote": 0,
                    "missing_from_local": 0,
                    "samples": [],
                }
                for local in samples:
                    remote = remote_record(requester, symbol, name, local)
                    key = "funding_time_utc_ms" if name == "funding" else "open_time_utc_ms"
                    if remote is None:
                        stats["missing_from_remote"] += 1
                        status = "MISSING_FROM_REMOTE"
                        differences: list[dict[str, Any]] = []
                    else:
                        differences = [
                            {"field": field, "local": str(local.get(field)), "remote": str(value)}
                            for field, value in remote.items()
                            if not fields_equal(field, local.get(field), value)
                        ]
                        status = "MISMATCHED" if differences else "MATCHED"
                        stats["mismatched" if differences else "matched"] += 1
                    stats["samples"].append(
                        {
                            "time_utc": utc_text(int(local[key])),
                            "status": status,
                            "differences": differences,
                        }
                    )
                stream_result[str(year)] = stats
                for metric in result["totals"]:
                    result["totals"][metric] += stats[metric]
            result["symbols"][symbol][name] = stream_result
    return result


def write_report(output: Path, name: str, value: Any) -> None:
    AtomicDatasetStore(output).write_json_atomic(name, value)


def run(output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    inventory, selected = discover()
    write_report(output, "source_inventory.json", inventory)
    earliest = {
        "symbols": {
            symbol: {
                name: {
                    "earliest_month": data["earliest_month"],
                    "latest_complete_archive_month": data["latest_month"],
                }
                for name, data in inventory["symbols"][symbol].items()
            }
            for symbol in SYMBOLS
        },
        "all_required_streams_common_start_utc": "2020-01-01T00:00:00Z",
        "all_required_streams_latest_complete_archive_month": min(
            data["latest_month"]
            for symbol in SYMBOLS
            for data in inventory["symbols"][symbol].values()
        ),
    }
    write_report(output, "earliest_availability.json", earliest)
    free = shutil.disk_usage(output).free
    resources = estimate_resources(tuple(item[-1] for item in selected), free_bytes=free)
    resources.update(
        {
            "estimated_record_counts": {
                "per_symbol_trade_1m": 3_419_520,
                "per_symbol_mark_1m": 3_419_520,
                "per_symbol_index_1m": 3_419_520,
                "per_symbol_trade_4h": 14_248,
                "per_symbol_trade_1d": 2_375,
                "per_symbol_funding": 7_125,
            },
            "estimated_http_requests": len(selected) * 2 + 588 + 6,
            "estimated_runtime_minutes": 45,
        }
    )
    write_report(output, "resource_estimate.json", resources)
    if resources["capacity_status"] != "SUFFICIENT":
        return "DISK_CAPACITY_INSUFFICIENT"
    archive_manifest_path = output / "archive_manifest.json"
    if archive_manifest_path.exists():
        archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
        manifests = archive_manifest["shards"]
        if len(manifests) != len(selected):
            raise ValueError("ARCHIVE_RESUME_SHARD_COUNT_MISMATCH")
    else:
        manifests = []
        started = time.time()
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(acquire_one, output, item): item for item in selected}
            for index, future in enumerate(as_completed(futures), 1):
                manifests.append(future.result())
                if index % 25 == 0:
                    print(f"archive shards completed: {index}/{len(selected)}", flush=True)
        manifests.sort(key=lambda item: (item["symbol"], item["stream_name"], item["month"]))
        archive_hashes = {
            f"{item['symbol']}|{item['stream_name']}|{item['month']}": item[
                "canonical_content_hash"
            ]
            for item in manifests
        }
        archive_manifest = {
            "source": ARCHIVE_BASE_URL,
            "shard_count": len(manifests),
            "elapsed_seconds": str(Decimal(str(time.time() - started)).quantize(Decimal("0.001"))),
            "shards": manifests,
            "archive_bundle_hash": versioned_content_bundle_hash(
                bundle_version="BINANCE_MONTHLY_ARCHIVE_BUNDLE_V1", dataset_hashes=archive_hashes
            ),
        }
        write_report(output, "archive_manifest.json", archive_manifest)
    prior = Path("artifacts/data_readiness/refreshed")
    prior_roots = sorted(prior.glob("*/acquisition_manifest.json"))
    rest_tail_path = output / "rest_tail_manifest.json"
    if rest_tail_path.exists():
        rest_tail = json.loads(rest_tail_path.read_text(encoding="utf-8"))
    else:
        rest_tail = {
            "source": "https://fapi.binance.com",
            "reuse_of_previously_audited_public_rest_tail": True,
            "manifest_path": str(prior_roots[-1].resolve()) if prior_roots else None,
            "status": "AVAILABLE" if prior_roots else "UNAVAILABLE",
        }
    if prior_roots:
        audited_tail_manifest = json.loads(prior_roots[-1].read_text(encoding="utf-8"))
        rest_tail["audited_tail_dataset_content_hash"] = audited_tail_manifest.get(
            "dataset_content_hash"
        )
    write_report(output, "rest_tail_manifest.json", rest_tail)
    gap_path = output / "historical_gap_report.json"
    coverage_path = output / "historical_coverage.json"
    if gap_path.exists() and coverage_path.exists():
        gaps = json.loads(gap_path.read_text(encoding="utf-8"))
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    else:
        gaps, coverage = validate_streams(output, manifests)
        write_report(output, "historical_gap_report.json", gaps)
        write_report(output, "historical_coverage.json", coverage)
    if "historical_gap_fill" not in rest_tail and any(
        gaps[symbol][name]["gap_count"] for symbol in SYMBOLS for name in ("mark_1m", "index_1m")
    ):
        rest_tail["historical_gap_fill"] = fill_price_gaps(output, gaps)
        write_report(output, "rest_tail_manifest.json", rest_tail)
        gaps, coverage = validate_streams(output, manifests)
        write_report(output, "historical_gap_report.json", gaps)
        write_report(output, "historical_coverage.json", coverage)
    cross_validation = gaps.get("native_cross_validation")
    if cross_validation is None:
        cross_validation = cross_validate_native(output)
        gaps["native_cross_validation"] = cross_validation
        write_report(output, "historical_gap_report.json", gaps)
    tail_coverage_path = Path("artifacts/data_readiness/local_coverage.json")
    tail_record_count = 0
    tail_disk_bytes = 0
    if tail_coverage_path.exists():
        tail_coverage = json.loads(tail_coverage_path.read_text(encoding="utf-8"))
        for symbol in SYMBOLS:
            for name, values in tail_coverage["symbols"][symbol].items():
                if name in coverage[symbol]:
                    coverage[symbol][name]["rest_tail_start_time_utc"] = values["start_time_utc"]
                    coverage[symbol][name]["final_latest_time_utc"] = values["end_close_time_utc"]
                    coverage[symbol][name]["rest_tail_record_count"] = values["record_count"]
                    tail_record_count += values["record_count"]
        tail_data_root = Path(tail_coverage["selected_snapshot_root"])
        tail_disk_bytes = sum(
            path.stat().st_size for path in tail_data_root.rglob("*") if path.is_file()
        )
        coverage["joint_final_latest_time_utc"] = min(
            coverage[symbol][name]["final_latest_time_utc"]
            for symbol in SYMBOLS
            for name in ("trade_1m", "mark_1m", "funding")
        )
        write_report(output, "historical_coverage.json", coverage)
    critical_failure = any(
        gaps[symbol][name]["gap_count"]
        or gaps[symbol][name]["duplicate_count"]
        or not gaps[symbol][name]["all_raw_checksums_match"]
        for symbol in SYMBOLS
        for name in ("trade_1m", "mark_1m", "funding")
    )
    cross_validation_failed = any(
        not cross_validation["symbols"][symbol][interval]["valid"]
        for symbol in SYMBOLS
        for interval in ("4h", "1d")
    )
    sample_path = output / "annual_sample_reconciliation.json"
    if sample_path.exists():
        samples = json.loads(sample_path.read_text(encoding="utf-8"))
    else:
        samples = reconcile(output)
        write_report(output, "annual_sample_reconciliation.json", samples)
    split = build_experiment_split_candidate(
        common_start_utc_ms=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000),
        latest_complete_month=earliest["all_required_streams_latest_complete_archive_month"],
    )
    write_report(output, "experiment_split_candidate.json", split)
    contract = {
        "version": "APPROXIMATED_CURRENT_RULES_V1",
        "historical_exchange_info_fabricated": False,
        "plans_analyzed": 0,
        "status": "EXECUTION_LEVEL_ANALYSIS_DEFERRED_UNTIL_2D",
        "required_2d_labels": ["CONTRACT_RULE_SENSITIVITY", "NOT_EXCHANGE_EXACT"],
        "reason": "This data-only task creates no ExecutionPlan or position quantity.",
    }
    maintenance = {
        "version": "APPROXIMATED_MAINTENANCE_MODEL_V1",
        "historical_maintenance_brackets_fabricated": False,
        "leverage": "1",
        "trades_analyzed": 0,
        "status": "TRADE_LEVEL_MATERIALITY_DEFERRED_UNTIL_2D",
        "required_2d_labels": [
            "APPROXIMATED_EXECUTION_INFRASTRUCTURE",
            "NOT_EXCHANGE_EXACT",
            "NOT_LIVE_ELIGIBLE",
        ],
        "reason": "This data-only task executes no trades and cannot compare stop/liquidation boundaries.",
    }
    write_report(output, "contract_rule_sensitivity.json", contract)
    write_report(output, "maintenance_materiality.json", maintenance)
    sample_failed = samples["totals"]["mismatched"] or samples["totals"]["missing_from_remote"]
    critical_gap_intervals = [
        {"symbol": symbol, "stream": name, **interval}
        for symbol in SYMBOLS
        for name in ("trade_1m", "mark_1m", "funding")
        for interval in gaps[symbol][name]["gap_intervals"]
    ]
    cross_validation_summary = {
        symbol: {
            interval: {
                "compared_bars": cross_validation["symbols"][symbol][interval]["compared_bars"],
                "issue_count": cross_validation["symbols"][symbol][interval]["issue_count"],
                "valid": cross_validation["symbols"][symbol][interval]["valid"],
            }
            for interval in ("4h", "1d")
        }
        for symbol in SYMBOLS
    }
    cross_validation_issue_count = sum(
        item["issue_count"]
        for symbol_result in cross_validation_summary.values()
        for item in symbol_result.values()
    )
    integrity_blockers = {
        "critical_gap_count": len(critical_gap_intervals),
        "critical_gap_intervals": critical_gap_intervals,
        "native_cross_validation_issue_count": cross_validation_issue_count,
        "native_cross_validation": cross_validation_summary,
        "annual_sample_failed": bool(sample_failed),
    }
    if critical_failure or cross_validation_failed or sample_failed:
        status = "DATA_INTEGRITY_FAILED"
    elif not split["coverage_sufficient"]:
        status = "DATA_COVERAGE_INSUFFICIENT"
    else:
        status = "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
    total_records = sum(item.get("record_count", 0) for item in manifests)
    rest_gap_fill_records = sum(
        item["record_count"] for item in rest_tail.get("historical_gap_fill", {}).get("gaps", [])
    )
    historical_canonical_records = sum(
        coverage[symbol][name]["record_count"] for symbol in SYMBOLS for name, *_unused in STREAMS
    )
    data_bytes = sum(path.stat().st_size for path in (output / "data").rglob("*") if path.is_file())
    content_dependencies = {
        "official_archive": archive_manifest["archive_bundle_hash"],
        "rest_gap_fill": rest_tail.get("historical_gap_fill", {}).get("manifest_hash", "NONE"),
        "audited_rest_tail": rest_tail.get("audited_tail_dataset_content_hash", "NONE"),
    }
    data_bundle_hash = versioned_content_bundle_hash(
        bundle_version="BINANCE_HISTORICAL_HYBRID_BUNDLE_V1",
        dataset_hashes=content_dependencies,
    )
    final = {
        "final_status": status,
        "two_d_authorized": status
        in {"READY_FOR_BASELINE_EVALUATION", "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"},
        "required_permanent_labels": [
            "APPROXIMATED_EXECUTION_INFRASTRUCTURE",
            "NOT_EXCHANGE_EXACT",
            "NOT_LIVE_ELIGIBLE",
        ]
        if status.endswith("WITH_APPROXIMATIONS")
        else [],
        "earliest_common_time_utc": "2020-01-01T00:00:00Z",
        "latest_complete_archive_month": earliest[
            "all_required_streams_latest_complete_archive_month"
        ],
        "total_archive_records": total_records,
        "rest_gap_fill_records": rest_gap_fill_records,
        "historical_canonical_records": historical_canonical_records,
        "rest_tail_records": tail_record_count,
        "combined_records": historical_canonical_records + tail_record_count,
        "data_disk_bytes": data_bytes,
        "rest_tail_disk_bytes": tail_disk_bytes,
        "combined_disk_bytes": data_bytes + tail_disk_bytes,
        "archive_bundle_hash": archive_manifest["archive_bundle_hash"],
        "data_bundle_hash": data_bundle_hash,
        "annual_sample_totals": samples["totals"],
        "integrity_blockers": integrity_blockers,
        "experiment_split_candidate": split,
        "contract_rule_policy": contract,
        "maintenance_policy": maintenance,
        "scope_attestation": {
            "modified_2a_2b_2c": False,
            "ran_2d": False,
            "api_key_used": False,
            "account_or_order_capability_used": False,
        },
    }
    write_report(output, "final_data_readiness_report.json", final)
    markdown = f"""# Binance Historical Data Readiness\n\nFinal status: `{status}`\n\n- Earliest common archive time: `2020-01-01T00:00:00Z`\n- Latest complete archive month: `{earliest["all_required_streams_latest_complete_archive_month"]}`\n- Archive records: `{total_records}`; REST gap-fill records: `{rest_gap_fill_records}`; historical Canonical records: `{historical_canonical_records}`; audited REST tail records: `{tail_record_count}`; combined records: `{historical_canonical_records + tail_record_count}`\n- Historical data bytes: `{data_bytes}`; audited REST tail bytes: `{tail_disk_bytes}`; combined disk bytes: `{data_bytes + tail_disk_bytes}`\n- Annual reconciliation: `{canonical_dumps(samples["totals"])}`\n- Official archive bundle hash: `{archive_manifest["archive_bundle_hash"]}`\n- Hybrid data bundle hash: `{data_bundle_hash}`\n- Critical trade/mark/funding gap intervals: `{len(critical_gap_intervals)}`\n- Native 4H/1D cross-validation issue bars: `{cross_validation_issue_count}`; see `historical_gap_report.json` for exact bars and fields.\n- Split: 250 daily pre-roll; Training 36 UTC months; Validation 12 UTC months; OOS 18 UTC months.\n- Approximation labels: `APPROXIMATED_EXECUTION_INFRASTRUCTURE`, `NOT_EXCHANGE_EXACT`, `NOT_LIVE_ELIGIBLE`.\n- 2A/2B/2C unchanged. 2D not run. No API key, account, or order capability used.\n"""
    (output / "final_data_readiness_report.md").write_text(markdown, encoding="utf-8", newline="\n")
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
