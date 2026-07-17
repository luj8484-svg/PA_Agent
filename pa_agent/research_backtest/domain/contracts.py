from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.domain.enums import (
    ApproximationDirection,
    ContractRuleMode,
    ContractRuleReviewStatus,
    ResearchStage,
)
from pa_agent.research_backtest.versions import (
    CONTRACT_APPROXIMATION_POLICY_VERSION,
    CONTRACT_RULE_COVERAGE_VERSION,
)

SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})


class ContractRuleExpiredError(ValueError):
    pass


class ContractRuleUnavailableError(ValueError):
    pass


def _validate_decimal(value: Decimal, name: str, *, positive: bool) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        label = "positive" if positive else "nonnegative minimum"
        raise ValueError(f"{name} must be {label}")


def _validate_covered(value: object) -> None:
    if value.symbol not in SUPPORTED_SYMBOLS:
        raise ValueError("unsupported contract symbol")
    require_utc_ms(value.query_time_utc_ms, "query_time_utc_ms")
    start = require_utc_ms(value.effective_from_utc_ms, "effective_from_utc_ms")
    end = require_utc_ms(value.effective_to_utc_ms, "effective_to_utc_ms")
    if start >= end:
        raise ValueError("contract effective interval must be nonempty")
    for name in ("source_kind", "source_uri_or_archive_id", "rule_version"):
        require_nonempty_string(getattr(value, name), name)
    for name in ("source_content_hash", "evidence_manifest_hash"):
        require_sha256(getattr(value, name), name)
    _validate_decimal(value.tick_size, "tick_size", positive=True)
    _validate_decimal(value.step_size, "step_size", positive=True)
    _validate_decimal(value.min_qty, "min_qty", positive=False)
    _validate_decimal(value.min_notional, "min_notional", positive=False)
    for name in ("quantity_precision_audit", "price_precision_audit"):
        audit = getattr(value, name)
        if type(audit) is not int or audit < 0:
            raise ValueError(f"{name} must be nonnegative integer")
    if value.created_by != "PYTHON_DETERMINISTIC":
        raise ValueError("contract coverage must be created by deterministic Python")


@dataclass(frozen=True, slots=True)
class VerifiedContractRuleCoverage:
    schema_version: str
    coverage_id: str
    coverage_content_hash: str
    mode: ContractRuleMode
    symbol: str
    query_time_utc_ms: int
    created_by: str
    source_kind: str
    source_uri_or_archive_id: str
    source_content_hash: str
    effective_from_utc_ms: int
    effective_to_utc_ms: int
    rule_version: str
    review_status: ContractRuleReviewStatus
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    quantity_precision_audit: int
    price_precision_audit: int
    evidence_manifest_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_RULE_COVERAGE_VERSION:
            raise ValueError("unsupported contract coverage schema")
        if self.mode is not ContractRuleMode.VERIFIED:
            raise ValueError("verified contract has wrong mode")
        if self.review_status is not ContractRuleReviewStatus.APPROVED_VERIFIED:
            raise ValueError("verified contract has wrong review status")
        _validate_covered(self)
        verify_formal_identity(
            self,
            id_field="coverage_id",
            hash_field="coverage_content_hash",
            prefix="cr_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class ApproximatedContractRuleCoverage:
    schema_version: str
    coverage_id: str
    coverage_content_hash: str
    mode: ContractRuleMode
    symbol: str
    query_time_utc_ms: int
    created_by: str
    source_kind: str
    source_uri_or_archive_id: str
    source_content_hash: str
    effective_from_utc_ms: int
    effective_to_utc_ms: int
    rule_version: str
    review_status: ContractRuleReviewStatus
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    quantity_precision_audit: int
    price_precision_audit: int
    evidence_manifest_hash: str
    approximation_method: str
    approximation_distance_ms: int
    evidence_time_utc_ms: int
    approximation_direction: ApproximationDirection
    approximation_policy_version: str
    approximation_watermark: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_RULE_COVERAGE_VERSION:
            raise ValueError("unsupported contract coverage schema")
        if self.mode is not ContractRuleMode.APPROXIMATED:
            raise ValueError("approximated contract has wrong mode")
        _validate_covered(self)
        require_nonempty_string(self.approximation_method, "approximation_method")
        require_utc_ms(self.approximation_distance_ms, "approximation_distance_ms")
        require_utc_ms(self.evidence_time_utc_ms, "evidence_time_utc_ms")
        if self.approximation_policy_version != CONTRACT_APPROXIMATION_POLICY_VERSION:
            raise ValueError("unsupported approximation policy")
        if self.approximation_watermark != "APPROXIMATED_NOT_LIVE_ELIGIBLE":
            raise ValueError("approximated contract requires its frozen watermark")
        if self.approximation_direction is ApproximationDirection.PRIOR_ONLY_APPROXIMATION:
            if self.review_status is not ContractRuleReviewStatus.APPROVED_PRIOR_ONLY:
                raise ValueError("prior approximation has wrong review status")
            if self.evidence_time_utc_ms > self.query_time_utc_ms:
                raise ValueError("prior approximation cannot use future evidence")
        elif (
            self.approximation_direction
            is ApproximationDirection.HINDSIGHT_DIAGNOSTIC_APPROXIMATION
        ):
            if self.review_status is not ContractRuleReviewStatus.APPROVED_HINDSIGHT_DIAGNOSTIC:
                raise ValueError("hindsight approximation has wrong review status")
            if self.evidence_time_utc_ms <= self.query_time_utc_ms:
                raise ValueError("hindsight approximation requires future diagnostic evidence")
        else:
            raise ValueError("invalid approximation direction")
        if self.approximation_distance_ms != abs(
            self.query_time_utc_ms - self.evidence_time_utc_ms
        ):
            raise ValueError("approximation distance does not match evidence time")
        verify_formal_identity(
            self,
            id_field="coverage_id",
            hash_field="coverage_content_hash",
            prefix="cr_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class UnavailableContractRuleCoverage:
    schema_version: str
    coverage_id: str
    coverage_content_hash: str
    mode: ContractRuleMode
    symbol: str
    query_time_utc_ms: int
    created_by: str
    unavailable_reason: str
    searched_archive_hashes: tuple[str, ...]
    requested_time_utc_ms: int

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_RULE_COVERAGE_VERSION:
            raise ValueError("unsupported contract coverage schema")
        if self.mode is not ContractRuleMode.UNAVAILABLE:
            raise ValueError("unavailable contract has wrong mode")
        if self.symbol not in SUPPORTED_SYMBOLS:
            raise ValueError("unsupported contract symbol")
        require_utc_ms(self.query_time_utc_ms, "query_time_utc_ms")
        if self.requested_time_utc_ms != self.query_time_utc_ms:
            raise ValueError("requested contract time must equal query time")
        require_nonempty_string(self.unavailable_reason, "unavailable_reason")
        if self.searched_archive_hashes != tuple(sorted(set(self.searched_archive_hashes))):
            raise ValueError("searched archive hashes must be unique and sorted")
        for value in self.searched_archive_hashes:
            require_sha256(value, "searched_archive_hash")
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("contract coverage must be created by deterministic Python")
        verify_formal_identity(
            self,
            id_field="coverage_id",
            hash_field="coverage_content_hash",
            prefix="cr_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


ContractRuleCoverage: TypeAlias = (
    VerifiedContractRuleCoverage
    | ApproximatedContractRuleCoverage
    | UnavailableContractRuleCoverage
)


def _covered_payload(**values: object) -> dict[str, object]:
    return {
        "schema_version": CONTRACT_RULE_COVERAGE_VERSION,
        "symbol": values["symbol"],
        "query_time_utc_ms": values["query_time_utc_ms"],
        "created_by": "PYTHON_DETERMINISTIC",
        "source_kind": values["source_kind"],
        "source_uri_or_archive_id": values["source_uri_or_archive_id"],
        "source_content_hash": values["source_content_hash"],
        "effective_from_utc_ms": values["effective_from_utc_ms"],
        "effective_to_utc_ms": values["effective_to_utc_ms"],
        "rule_version": values["rule_version"],
        "tick_size": values["tick_size"],
        "step_size": values["step_size"],
        "min_qty": values["min_qty"],
        "min_notional": values["min_notional"],
        "quantity_precision_audit": values["quantity_precision_audit"],
        "price_precision_audit": values["price_precision_audit"],
        "evidence_manifest_hash": values["evidence_manifest_hash"],
    }


def verified_contract_rule(**values: object) -> VerifiedContractRuleCoverage:
    payload = {
        **_covered_payload(**values),
        "mode": ContractRuleMode.VERIFIED,
        "review_status": ContractRuleReviewStatus.APPROVED_VERIFIED,
    }
    coverage_id, digest = formal_identity("cr_", payload)
    return VerifiedContractRuleCoverage(
        coverage_id=coverage_id,
        coverage_content_hash=digest,
        **payload,
    )


def approximated_contract_rule(**values: object) -> ApproximatedContractRuleCoverage:
    payload = {
        **_covered_payload(**values),
        "mode": ContractRuleMode.APPROXIMATED,
        "review_status": values["review_status"],
        "approximation_method": values["approximation_method"],
        "approximation_distance_ms": values["approximation_distance_ms"],
        "evidence_time_utc_ms": values["evidence_time_utc_ms"],
        "approximation_direction": values["approximation_direction"],
        "approximation_policy_version": CONTRACT_APPROXIMATION_POLICY_VERSION,
        "approximation_watermark": "APPROXIMATED_NOT_LIVE_ELIGIBLE",
    }
    coverage_id, digest = formal_identity("cr_", payload)
    return ApproximatedContractRuleCoverage(
        coverage_id=coverage_id,
        coverage_content_hash=digest,
        **payload,
    )


def unavailable_contract_rule(
    *,
    symbol: str,
    query_time_utc_ms: int,
    unavailable_reason: str,
    searched_archive_hashes: tuple[str, ...],
) -> UnavailableContractRuleCoverage:
    payload = {
        "schema_version": CONTRACT_RULE_COVERAGE_VERSION,
        "mode": ContractRuleMode.UNAVAILABLE,
        "symbol": symbol,
        "query_time_utc_ms": query_time_utc_ms,
        "created_by": "PYTHON_DETERMINISTIC",
        "unavailable_reason": unavailable_reason,
        "searched_archive_hashes": tuple(sorted(searched_archive_hashes)),
        "requested_time_utc_ms": query_time_utc_ms,
    }
    coverage_id, digest = formal_identity("cr_", payload)
    return UnavailableContractRuleCoverage(
        coverage_id=coverage_id,
        coverage_content_hash=digest,
        **payload,
    )


def ensure_contract_usable(
    coverage: ContractRuleCoverage,
    stage: ResearchStage,
) -> VerifiedContractRuleCoverage | ApproximatedContractRuleCoverage:
    if isinstance(coverage, UnavailableContractRuleCoverage):
        raise ContractRuleUnavailableError("contract rule is unavailable")
    if (
        not coverage.effective_from_utc_ms
        <= coverage.query_time_utc_ms
        < coverage.effective_to_utc_ms
    ):
        raise ContractRuleExpiredError("contract rule does not cover the target")
    if isinstance(coverage, ApproximatedContractRuleCoverage):
        if stage is ResearchStage.LIVE_ELIGIBILITY_RESEARCH:
            raise ValueError("approximated rules are never live eligible")
        if (
            coverage.approximation_direction
            is ApproximationDirection.HINDSIGHT_DIAGNOSTIC_APPROXIMATION
            and stage is not ResearchStage.BACKTEST
        ):
            raise ValueError("hindsight approximation is diagnostic only")
    return coverage
