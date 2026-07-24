from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from pa_agent.research_data.normalize import (
    normalize_price_kline,
    normalize_trade_kline,
)

ARCHIVE_HOST = "data.binance.vision"
ARCHIVE_BASE_URL = f"https://{ARCHIVE_HOST}"
S3_LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
SPLIT_VERSION = "EXPERIMENT_SPLIT_CANDIDATE_V1"


@dataclass(frozen=True, slots=True)
class ArchiveObject:
    key: str
    size_bytes: int
    etag: str
    last_modified: str


def validate_archive_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ARCHIVE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OFFICIAL_ARCHIVE_ONLY")
    if not parsed.path.startswith("/data/futures/um/monthly/"):
        raise ValueError("MONTHLY_ARCHIVE_ONLY")
    return url


def parse_s3_listing(payload: bytes) -> tuple[tuple[ArchiveObject, ...], str | None]:
    root = ElementTree.fromstring(payload)
    namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    objects: list[ArchiveObject] = []
    for content in root.findall("s3:Contents", namespace):
        key = content.findtext("s3:Key", namespaces=namespace)
        size = content.findtext("s3:Size", namespaces=namespace)
        etag = content.findtext("s3:ETag", namespaces=namespace)
        modified = content.findtext("s3:LastModified", namespaces=namespace)
        if key is None or size is None or etag is None or modified is None:
            raise ValueError("INVALID_S3_LISTING")
        objects.append(
            ArchiveObject(
                key=key,
                size_bytes=int(size),
                etag=etag.strip('"'),
                last_modified=modified,
            )
        )
    truncated = root.findtext("s3:IsTruncated", default="false", namespaces=namespace)
    marker = root.findtext("s3:NextMarker", namespaces=namespace)
    if truncated == "true" and not marker:
        raise ValueError("TRUNCATED_LISTING_WITHOUT_MARKER")
    return tuple(objects), marker


def _parse_month(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%Y-%m")
    return parsed.year, parsed.month


def _add_months(value: str, count: int) -> str:
    year, month = _parse_month(value)
    ordinal = year * 12 + month - 1 + count
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


def month_range(start: str, end: str) -> tuple[str, ...]:
    start_year, start_month = _parse_month(start)
    end_year, end_month = _parse_month(end)
    first = start_year * 12 + start_month - 1
    last = end_year * 12 + end_month - 1
    if first > last:
        raise ValueError("start month follows end month")
    return tuple(f"{item // 12:04d}-{item % 12 + 1:02d}" for item in range(first, last + 1))


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _month_start(month: str) -> datetime:
    year, number = _parse_month(month)
    return datetime(year, number, 1, tzinfo=UTC)


def _month_end(month: str) -> datetime:
    return _month_start(_add_months(month, 1)) - timedelta(milliseconds=1)


def _segment(start_month: str, count: int) -> dict[str, Any]:
    end_month = _add_months(start_month, count - 1)
    return {
        "start_utc": _utc_text(_month_start(start_month)),
        "end_utc": _utc_text(_month_end(end_month)),
        "complete_utc_months": count,
    }


def build_experiment_split_candidate(
    *, common_start_utc_ms: int, latest_complete_month: str
) -> dict[str, Any]:
    common_start = datetime.fromtimestamp(common_start_utc_ms / 1_000, tz=UTC)
    pre_roll_end = common_start + timedelta(days=250) - timedelta(milliseconds=1)
    training_start = _add_months(pre_roll_end.strftime("%Y-%m"), 1)
    training = _segment(training_start, 36)
    validation_start = _add_months(training_start, 36)
    validation = _segment(validation_start, 12)
    oos_start = _add_months(validation_start, 12)
    oos = _segment(oos_start, 18)
    latest_end = _month_end(latest_complete_month)
    oos_end = datetime.fromisoformat(oos["end_utc"].replace("Z", "+00:00"))
    sufficient = oos_end <= latest_end
    result: dict[str, Any] = {
        "version": SPLIT_VERSION,
        "split_method": "STRICT_UTC_CALENDAR_MONTHS_NO_RANDOM_SPLIT",
        "oos_must_not_select_strategy_or_parameters": True,
        "pre_roll": {
            "start_utc": _utc_text(common_start),
            "end_utc": _utc_text(pre_roll_end),
            "complete_1d_bars": 250,
        },
        "training": training,
        "validation": validation,
        "oos": oos,
        "latest_complete_month": latest_complete_month,
        "coverage_sufficient": sufficient,
    }
    if not sufficient:
        result["failure"] = "DATA_COVERAGE_INSUFFICIENT"
    return result


def estimate_resources(objects: tuple[ArchiveObject, ...], *, free_bytes: int) -> dict[str, Any]:
    if free_bytes < 0:
        raise ValueError("free_bytes must be nonnegative")
    compressed = sum(item.size_bytes for item in objects)
    extracted = compressed * 7
    canonical = compressed * 10
    manifests = max(1_048_576, len(objects) * 4_096)
    final_bytes = compressed + canonical + manifests
    required = (final_bytes * 3 + 1) // 2
    return {
        "archive_object_count": len(objects),
        "compressed_bytes": compressed,
        "estimated_extracted_temporary_bytes": extracted,
        "estimated_canonical_bytes": canonical,
        "estimated_manifest_bytes": manifests,
        "estimated_final_bytes": final_bytes,
        "safety_multiplier": "1.5",
        "required_free_bytes": required,
        "available_free_bytes": free_bytes,
        "capacity_status": "SUFFICIENT" if free_bytes >= required else "DISK_CAPACITY_INSUFFICIENT",
    }


def fields_equal(field: str, left: Any, right: Any) -> bool:
    if field.endswith("_utc_ms") or field == "trade_count":
        return int(left) == int(right)
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return left == right


def parse_checksum(text: str, expected_filename: str) -> str:
    parts = text.strip().split()
    if len(parts) != 2 or len(parts[0]) != 64:
        raise ValueError("INVALID_SHA256_CHECKSUM")
    try:
        int(parts[0], 16)
    except ValueError as exc:
        raise ValueError("INVALID_SHA256_CHECKSUM") from exc
    if parts[1].lstrip("*") != expected_filename:
        raise ValueError("CHECKSUM_FILENAME_MISMATCH")
    return parts[0].lower()


def canonicalize_csv_rows(
    rows: list[list[str]], *, symbol: str, stream: str, interval: str | None
) -> tuple[dict[str, Any], ...]:
    if not rows:
        return ()
    first = rows[0][0].strip().lower()
    data_rows = rows[1:] if not first.lstrip("-").isdigit() else rows
    records: list[dict[str, Any]] = []
    if stream == "funding":
        for row in data_rows:
            if len(row) != 3:
                raise ValueError("INVALID_ARCHIVE_FUNDING_ROW")
            rate = Decimal(row[2])
            if not rate.is_finite():
                raise ValueError("NON_FINITE_FUNDING_RATE")
            records.append(
                {
                    "funding_interval_hours": int(row[1]),
                    "funding_rate": str(rate),
                    "funding_time_utc_ms": int(row[0]),
                    "schema_version": "BINANCE_ARCHIVE_FUNDING_V1",
                    "source": "binance_data_vision",
                    "symbol": symbol,
                }
            )
        return tuple(records)
    if interval is None:
        raise ValueError("Kline interval is required")
    for row in data_rows:
        if stream == "trade":
            record = normalize_trade_kline(
                row,
                symbol=symbol,
                interval=interval,
                source_server_time_utc_ms=2**63 - 1,
            )
        elif stream in {"mark", "index"}:
            record = normalize_price_kline(
                row,
                stream=stream,
                symbol=symbol,
                interval=interval,
                source_server_time_utc_ms=2**63 - 1,
            )
        else:
            raise ValueError(f"Unsupported archive stream: {stream}")
        item = asdict(record)
        item = {
            key: str(value) if isinstance(value, Decimal) else value for key, value in item.items()
        }
        item["source"] = "binance_data_vision"
        records.append(item)
    return tuple(records)
