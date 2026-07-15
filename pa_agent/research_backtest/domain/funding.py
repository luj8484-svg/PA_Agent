from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.domain.enums import FundingRiskVerificationMode
from pa_agent.research_backtest.versions import (
    FUNDING_RISK_CONFIG_SNAPSHOT_SCHEMA_VERSION,
    FUNDING_RISK_CONFIG_VERSION,
    FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_VERSION,
)

SETTLEMENT_BOUNDARY_SEMANTICS = "CONSERVATIVE_WINDOW_V1"


class FundingScheduleUnverifiedError(ValueError):
    pass


class FundingRiskConfigUnavailableError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SettlementWindow:
    window_start_utc_ms: int
    nominal_time_utc_ms: int
    window_end_utc_ms: int

    def __post_init__(self) -> None:
        require_utc_ms(self.window_start_utc_ms, "window_start_utc_ms")
        require_utc_ms(self.nominal_time_utc_ms, "nominal_time_utc_ms")
        require_utc_ms(self.window_end_utc_ms, "window_end_utc_ms")
        if not self.window_start_utc_ms <= self.nominal_time_utc_ms <= self.window_end_utc_ms:
            raise ValueError("funding window must contain its nominal time")


def settlement_window(start: int, nominal: int, end: int) -> SettlementWindow:
    return SettlementWindow(start, nominal, end)


@dataclass(frozen=True, slots=True)
class FundingScheduleSnapshot:
    schema_version: str
    schedule_id: str
    schedule_content_hash: str
    symbol: str
    schedule_version: str
    effective_from_utc_ms: int
    effective_to_utc_ms: int
    timezone: str
    nominal_timestamps_utc_ms: tuple[int, ...]
    settlement_windows: tuple[SettlementWindow, ...]
    settlement_boundary_semantics: str
    window_tolerance_ms: int
    source_manifest_hash: str
    created_by: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported funding schedule schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported funding schedule symbol")
        require_nonempty_string(self.schedule_version, "schedule_version")
        start = require_utc_ms(self.effective_from_utc_ms, "effective_from_utc_ms")
        end = require_utc_ms(self.effective_to_utc_ms, "effective_to_utc_ms")
        if start >= end:
            raise ValueError("funding schedule effective interval must be nonempty")
        if self.timezone != "UTC":
            raise ValueError("funding schedule timezone must be UTC")
        if self.nominal_timestamps_utc_ms != tuple(
            window.nominal_time_utc_ms for window in self.settlement_windows
        ):
            raise ValueError("funding nominal timestamps must match windows")
        if self.nominal_timestamps_utc_ms != tuple(sorted(set(self.nominal_timestamps_utc_ms))):
            raise ValueError("funding nominal timestamps must be strictly increasing")
        for previous, current in zip(
            self.settlement_windows, self.settlement_windows[1:], strict=False
        ):
            if previous.window_end_utc_ms >= current.window_start_utc_ms:
                raise ValueError("funding settlement windows must not overlap")
        if any(
            window.window_start_utc_ms < start or window.window_end_utc_ms > end
            for window in self.settlement_windows
        ):
            raise ValueError("funding windows must be inside schedule validity")
        if self.settlement_boundary_semantics != SETTLEMENT_BOUNDARY_SEMANTICS:
            raise ValueError("unsupported funding boundary semantics")
        require_utc_ms(self.window_tolerance_ms, "window_tolerance_ms")
        require_sha256(self.source_manifest_hash, "source_manifest_hash")
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("funding schedule must be created by deterministic Python")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="schedule_id",
            hash_field="schedule_content_hash",
            prefix="fsched_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class CoveredFundingRiskConfigSnapshot:
    schema_version: str
    config_id: str
    content_hash: str
    symbol: str
    adverse_rate_cap: Decimal
    effective_from_utc_ms: int
    effective_to_utc_ms: int
    source_kind: str
    source_manifest_hash: str
    verification_mode: FundingRiskVerificationMode
    stress_multiplier: Decimal
    version: str
    watermark: str
    evidence_time_utc_ms: int
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != FUNDING_RISK_CONFIG_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported funding risk config schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported funding risk symbol")
        if self.verification_mode not in {
            FundingRiskVerificationMode.VERIFIED,
            FundingRiskVerificationMode.APPROXIMATED,
        }:
            raise ValueError("covered funding risk config has invalid mode")
        if (
            not isinstance(self.adverse_rate_cap, Decimal)
            or not self.adverse_rate_cap.is_finite()
            or self.adverse_rate_cap < 0
        ):
            raise ValueError("adverse funding rate cap must be finite and nonnegative")
        start = require_utc_ms(self.effective_from_utc_ms, "effective_from_utc_ms")
        end = require_utc_ms(self.effective_to_utc_ms, "effective_to_utc_ms")
        if start >= end:
            raise ValueError("funding risk effective interval must be nonempty")
        require_nonempty_string(self.source_kind, "source_kind")
        require_sha256(self.source_manifest_hash, "source_manifest_hash")
        if (
            not isinstance(self.stress_multiplier, Decimal)
            or not self.stress_multiplier.is_finite()
            or self.stress_multiplier < 1
        ):
            raise ValueError("funding stress multiplier must be at least one")
        if self.version != FUNDING_RISK_CONFIG_VERSION:
            raise ValueError("unsupported funding risk config version")
        if self.verification_mode is FundingRiskVerificationMode.VERIFIED:
            if self.watermark != "VERIFIED":
                raise ValueError("verified funding risk config has wrong watermark")
        elif self.watermark != "BASELINE_ASSUMPTION_NOT_VERIFIED":
            raise ValueError("approximated funding risk config requires its watermark")
        require_utc_ms(self.evidence_time_utc_ms, "evidence_time_utc_ms")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="config_id",
            hash_field="content_hash",
            prefix="frisk_",
        )


@dataclass(frozen=True, slots=True)
class UnavailableFundingRiskConfigSnapshot:
    schema_version: str
    config_id: str
    content_hash: str
    symbol: str
    verification_mode: FundingRiskVerificationMode
    version: str
    watermark: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != FUNDING_RISK_CONFIG_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported funding risk config schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported funding risk symbol")
        if self.verification_mode is not FundingRiskVerificationMode.UNAVAILABLE:
            raise ValueError("unavailable funding risk config has wrong mode")
        if self.version != FUNDING_RISK_CONFIG_VERSION:
            raise ValueError("unsupported funding risk config version")
        require_nonempty_string(self.watermark, "watermark")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="config_id",
            hash_field="content_hash",
            prefix="frisk_",
        )


FundingRiskConfigSnapshot: TypeAlias = (
    CoveredFundingRiskConfigSnapshot | UnavailableFundingRiskConfigSnapshot
)


def funding_schedule_snapshot(
    *,
    symbol: str,
    schedule_version: str,
    effective_from_utc_ms: int,
    effective_to_utc_ms: int,
    settlement_windows: tuple[SettlementWindow, ...],
    window_tolerance_ms: int,
    source_manifest_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> FundingScheduleSnapshot:
    payload = {
        "schema_version": FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "schedule_version": schedule_version,
        "effective_from_utc_ms": effective_from_utc_ms,
        "effective_to_utc_ms": effective_to_utc_ms,
        "timezone": "UTC",
        "nominal_timestamps_utc_ms": tuple(
            window.nominal_time_utc_ms for window in settlement_windows
        ),
        "settlement_windows": settlement_windows,
        "settlement_boundary_semantics": SETTLEMENT_BOUNDARY_SEMANTICS,
        "window_tolerance_ms": window_tolerance_ms,
        "source_manifest_hash": source_manifest_hash,
        "created_by": "PYTHON_DETERMINISTIC",
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    schedule_id, digest = formal_identity("fsched_", payload)
    return FundingScheduleSnapshot(
        schedule_id=schedule_id,
        schedule_content_hash=digest,
        **payload,
    )


def covered_funding_risk_config(
    *,
    symbol: str,
    target_time_utc_ms: int,
    adverse_rate_cap: Decimal,
    effective_from_utc_ms: int,
    effective_to_utc_ms: int,
    source_kind: str,
    source_manifest_hash: str,
    verification_mode: str | FundingRiskVerificationMode,
    stress_multiplier: Decimal,
    watermark: str,
    evidence_time_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> CoveredFundingRiskConfigSnapshot:
    mode = FundingRiskVerificationMode(verification_mode)
    if not effective_from_utc_ms <= target_time_utc_ms < effective_to_utc_ms:
        raise ValueError("funding risk config lacks target coverage")
    if evidence_time_utc_ms > target_time_utc_ms:
        raise ValueError("funding risk config cannot use future evidence")
    payload = {
        "schema_version": FUNDING_RISK_CONFIG_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "adverse_rate_cap": adverse_rate_cap,
        "effective_from_utc_ms": effective_from_utc_ms,
        "effective_to_utc_ms": effective_to_utc_ms,
        "source_kind": source_kind,
        "source_manifest_hash": source_manifest_hash,
        "verification_mode": mode,
        "stress_multiplier": stress_multiplier,
        "version": FUNDING_RISK_CONFIG_VERSION,
        "watermark": watermark,
        "evidence_time_utc_ms": evidence_time_utc_ms,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    config_id, digest = formal_identity("frisk_", payload)
    return CoveredFundingRiskConfigSnapshot(
        config_id=config_id,
        content_hash=digest,
        **payload,
    )


def unavailable_funding_risk_config(
    *,
    symbol: str,
    target_time_utc_ms: int,
    watermark: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> UnavailableFundingRiskConfigSnapshot:
    require_utc_ms(target_time_utc_ms, "target_time_utc_ms")
    payload = {
        "schema_version": FUNDING_RISK_CONFIG_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "verification_mode": FundingRiskVerificationMode.UNAVAILABLE,
        "version": FUNDING_RISK_CONFIG_VERSION,
        "watermark": watermark,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    config_id, digest = formal_identity("frisk_", payload)
    return UnavailableFundingRiskConfigSnapshot(
        config_id=config_id,
        content_hash=digest,
        **payload,
    )
