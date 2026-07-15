from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.versions import (
    TARGET_EVENT_WATERMARK_SCHEMA_VERSION,
    TARGET_MINUTE_OPEN_SNAPSHOT_SCHEMA_VERSION,
)

SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})


@dataclass(frozen=True, slots=True)
class TargetMinuteOpenSnapshot:
    schema_version: str
    snapshot_id: str
    snapshot_content_hash: str
    symbol: str
    stream: str
    open_time_utc_ms: int
    open_price: Decimal
    source_event_id: str
    source_stream_version: str
    created_by: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != TARGET_MINUTE_OPEN_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported target-minute open schema version")
        if self.symbol not in SUPPORTED_SYMBOLS or self.stream != "trade":
            raise ValueError("target open must be a supported trade stream")
        require_utc_ms(self.open_time_utc_ms, "open_time_utc_ms")
        if (
            not isinstance(self.open_price, Decimal)
            or not self.open_price.is_finite()
            or self.open_price <= 0
        ):
            raise ValueError("target open price must be finite and positive Decimal")
        require_nonempty_string(self.source_stream_version, "source_stream_version")
        expected_source_hash = canonical_sha256(
            {
                "symbol": self.symbol,
                "stream": self.stream,
                "open_time_utc_ms": self.open_time_utc_ms,
                "open_price": self.open_price,
                "source_stream_version": self.source_stream_version,
            }
        )
        if self.source_event_id != f"tmopen_source_{expected_source_hash[:24]}":
            raise ValueError("source_event_id does not match the open-event content")
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("target open must be created by deterministic Python")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="snapshot_id",
            hash_field="snapshot_content_hash",
            prefix="tmopen_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class TargetEventWatermark:
    schema_version: str
    watermark_id: str
    watermark_content_hash: str
    symbol: str
    target_open_time_utc_ms: int
    event_watermark_time_utc_ms: int
    watermark_source_event_id: str
    watermark_source_stream_version: str
    created_by: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != TARGET_EVENT_WATERMARK_SCHEMA_VERSION:
            raise ValueError("unsupported target-event watermark schema version")
        if self.symbol not in SUPPORTED_SYMBOLS:
            raise ValueError("unsupported watermark symbol")
        require_utc_ms(self.target_open_time_utc_ms, "target_open_time_utc_ms")
        require_utc_ms(self.event_watermark_time_utc_ms, "event_watermark_time_utc_ms")
        require_nonempty_string(self.watermark_source_event_id, "watermark_source_event_id")
        require_nonempty_string(
            self.watermark_source_stream_version, "watermark_source_stream_version"
        )
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("watermark must be created by deterministic Python")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="watermark_id",
            hash_field="watermark_content_hash",
            prefix="tmark_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def target_minute_open_snapshot(
    *,
    symbol: str,
    open_time_utc_ms: int,
    open_price: Decimal,
    source_stream_version: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> TargetMinuteOpenSnapshot:
    source_hash = canonical_sha256(
        {
            "symbol": symbol,
            "stream": "trade",
            "open_time_utc_ms": open_time_utc_ms,
            "open_price": open_price,
            "source_stream_version": source_stream_version,
        }
    )
    payload = {
        "schema_version": TARGET_MINUTE_OPEN_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "stream": "trade",
        "open_time_utc_ms": open_time_utc_ms,
        "open_price": open_price,
        "source_event_id": f"tmopen_source_{source_hash[:24]}",
        "source_stream_version": source_stream_version,
        "created_by": "PYTHON_DETERMINISTIC",
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    snapshot_id, digest = formal_identity("tmopen_", payload)
    return TargetMinuteOpenSnapshot(
        snapshot_id=snapshot_id,
        snapshot_content_hash=digest,
        **payload,
    )


def target_event_watermark(
    *,
    symbol: str,
    target_open_time_utc_ms: int,
    event_watermark_time_utc_ms: int,
    watermark_source_event_id: str,
    watermark_source_stream_version: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> TargetEventWatermark:
    payload = {
        "schema_version": TARGET_EVENT_WATERMARK_SCHEMA_VERSION,
        "symbol": symbol,
        "target_open_time_utc_ms": target_open_time_utc_ms,
        "event_watermark_time_utc_ms": event_watermark_time_utc_ms,
        "watermark_source_event_id": watermark_source_event_id,
        "watermark_source_stream_version": watermark_source_stream_version,
        "created_by": "PYTHON_DETERMINISTIC",
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    watermark_id, digest = formal_identity("tmark_", payload)
    return TargetEventWatermark(
        watermark_id=watermark_id,
        watermark_content_hash=digest,
        **payload,
    )
