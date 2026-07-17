from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.accounts import AccountPlanningSnapshot
from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import ResolutionKind
from pa_agent.research_backtest.versions import (
    ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    CANONICAL_2B_VERSION,
    PLANNING_PHASE_VERSION,
    PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION,
    PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION,
    PORTFOLIO_PLANNING_BATCH_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class ExpectedIntentRef:
    entry_intent_id: str
    symbol: str
    eligible_time_utc_ms: int

    def __post_init__(self) -> None:
        require_nonempty_string(self.entry_intent_id, "entry_intent_id")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported expected Intent symbol")
        require_utc_ms(self.eligible_time_utc_ms, "eligible_time_utc_ms")


@dataclass(frozen=True, slots=True)
class ResolutionRef:
    entry_intent_id: str
    symbol: str
    resolution_kind: ResolutionKind
    resolution_object_id: str
    resolution_content_hash: str

    def __post_init__(self) -> None:
        require_nonempty_string(self.entry_intent_id, "entry_intent_id")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported resolution symbol")
        if not isinstance(self.resolution_kind, ResolutionKind):
            raise ValueError("unsupported resolution kind")
        require_nonempty_string(self.resolution_object_id, "resolution_object_id")
        require_sha256(self.resolution_content_hash, "resolution_content_hash")
        if self.resolution_kind is ResolutionKind.SIZING_RESULT:
            if not self.resolution_object_id.startswith("size_"):
                raise ValueError("sizing resolution must reference a sizing result")
        elif not self.resolution_object_id.startswith("rej_"):
            raise ValueError("failed resolution must reference an ExecutionRejection")


@dataclass(frozen=True, slots=True)
class PortfolioBatchCompletenessSnapshot:
    schema_version: str
    completeness_id: str
    completeness_content_hash: str
    eligible_time_utc_ms: int
    expected_entry_intent_ids: tuple[str, ...]
    expected_symbols: tuple[str, ...]
    ordered_resolution_refs: tuple[ResolutionRef, ...]
    completeness_event_time_utc_ms: int
    completeness_policy_version: str
    source_event_id: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported batch completeness schema")
        require_utc_ms(self.eligible_time_utc_ms, "eligible_time_utc_ms")
        require_utc_ms(self.completeness_event_time_utc_ms, "completeness_event_time_utc_ms")
        if self.completeness_event_time_utc_ms < self.eligible_time_utc_ms:
            raise ValueError("completeness event time precedes eligible time")
        if not self.expected_entry_intent_ids:
            raise ValueError("expected Intent set must be nonempty")
        if len(set(self.expected_entry_intent_ids)) != len(self.expected_entry_intent_ids):
            raise ValueError("expected Intent IDs must be unique")
        if self.expected_symbols != tuple(sorted(set(self.expected_symbols))):
            raise ValueError("expected symbols must be unique and sorted")
        if len(self.expected_symbols) != len(self.expected_entry_intent_ids):
            raise ValueError("expected symbols and Intents must be one-to-one")
        resolution_ids = tuple(item.entry_intent_id for item in self.ordered_resolution_refs)
        if resolution_ids != self.expected_entry_intent_ids:
            raise ValueError("each expected Intent requires exactly one resolution")
        resolution_symbols = tuple(item.symbol for item in self.ordered_resolution_refs)
        if resolution_symbols != self.expected_symbols:
            raise ValueError("resolution symbols do not match expected Intents")
        if self.completeness_policy_version != PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION:
            raise ValueError("unsupported completeness policy")
        require_nonempty_string(self.source_event_id, "source_event_id")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="completeness_id",
            hash_field="completeness_content_hash",
            prefix="bcomplete_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class PortfolioPlanningBatch:
    schema_version: str
    batch_id: str
    batch_content_hash: str
    eligible_time_utc_ms: int
    completeness_snapshot_id: str
    completeness_snapshot_content_hash: str
    ordered_entry_intent_ids: tuple[str, ...]
    ordered_resolution_refs: tuple[ResolutionRef, ...]
    ordered_successful_sizing_result_ids: tuple[str, ...]
    ordered_symbols: tuple[str, ...]
    account_snapshot_id: str
    account_snapshot_hash: str
    target_open_snapshot_ids: tuple[str, ...]
    batch_config_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_PLANNING_BATCH_SCHEMA_VERSION:
            raise ValueError("unsupported portfolio planning batch schema")
        require_utc_ms(self.eligible_time_utc_ms, "eligible_time_utc_ms")
        expected_successes = tuple(
            item.resolution_object_id
            for item in self.ordered_resolution_refs
            if item.resolution_kind is ResolutionKind.SIZING_RESULT
        )
        if self.ordered_successful_sizing_result_ids != expected_successes:
            raise ValueError("batch successful sizing projection is inconsistent")
        if len(self.target_open_snapshot_ids) != len(expected_successes):
            raise ValueError("target-open IDs must match successful sizing rows")
        require_sha256(self.completeness_snapshot_content_hash, "completeness hash")
        require_sha256(self.account_snapshot_hash, "account_snapshot_hash")
        require_sha256(self.batch_config_hash, "batch_config_hash")
        if self.batch_config_hash != batch_config_hash():
            raise ValueError("batch config hash does not match frozen versions")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="batch_id",
            hash_field="batch_content_hash",
            prefix="pbatch_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def batch_config_hash() -> str:
    return canonical_sha256(
        {
            "batch_schema_version": PORTFOLIO_PLANNING_BATCH_SCHEMA_VERSION,
            "completeness_snapshot_schema_version": PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION,
            "completeness_policy_version": PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION,
            "sorting_policy_version": "SYMBOL_INTENT_ID_V1",
            "planning_phase_version": PLANNING_PHASE_VERSION,
            "account_evidence_bundle_schema_version": ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "canonical_version": CANONICAL_2B_VERSION,
        }
    )


def expected_intent_ref(
    entry_intent_id: str, symbol: str, eligible_time_utc_ms: int
) -> ExpectedIntentRef:
    return ExpectedIntentRef(entry_intent_id, symbol, eligible_time_utc_ms)


def resolution_ref(
    entry_intent_id: str,
    symbol: str,
    resolution_kind: ResolutionKind,
    resolution_object_id: str,
    resolution_content_hash: str,
) -> ResolutionRef:
    return ResolutionRef(
        entry_intent_id,
        symbol,
        resolution_kind,
        resolution_object_id,
        resolution_content_hash,
    )


def portfolio_batch_completeness_snapshot(
    expected_intents: tuple[ExpectedIntentRef, ...],
    resolutions: tuple[ResolutionRef, ...],
    *,
    completeness_event_time_utc_ms: int,
    source_event_id: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> PortfolioBatchCompletenessSnapshot:
    if not expected_intents:
        raise ValueError("expected Intent set must be nonempty")
    eligible_times = {item.eligible_time_utc_ms for item in expected_intents}
    if len(eligible_times) != 1:
        raise ValueError("expected Intents must share one eligible time")
    ordered_expected = tuple(
        sorted(expected_intents, key=lambda item: (item.symbol, item.entry_intent_id))
    )
    ordered_resolutions = tuple(
        sorted(resolutions, key=lambda item: (item.symbol, item.entry_intent_id))
    )
    payload = {
        "schema_version": PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION,
        "eligible_time_utc_ms": next(iter(eligible_times)),
        "expected_entry_intent_ids": tuple(item.entry_intent_id for item in ordered_expected),
        "expected_symbols": tuple(item.symbol for item in ordered_expected),
        "ordered_resolution_refs": ordered_resolutions,
        "completeness_event_time_utc_ms": completeness_event_time_utc_ms,
        "completeness_policy_version": PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION,
        "source_event_id": source_event_id,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    completeness_id, digest = formal_identity("bcomplete_", payload)
    return PortfolioBatchCompletenessSnapshot(
        completeness_id=completeness_id,
        completeness_content_hash=digest,
        **payload,
    )


def portfolio_planning_batch(
    completeness: PortfolioBatchCompletenessSnapshot,
    account: AccountPlanningSnapshot,
    *,
    target_open_snapshot_ids: tuple[str, ...],
    code_commit: str,
    dependency_lock_hash: str,
) -> PortfolioPlanningBatch:
    if account.event_time_utc_ms != completeness.eligible_time_utc_ms:
        raise ValueError("account snapshot time does not match batch eligible time")
    successful = tuple(
        item.resolution_object_id
        for item in completeness.ordered_resolution_refs
        if item.resolution_kind is ResolutionKind.SIZING_RESULT
    )
    payload = {
        "schema_version": PORTFOLIO_PLANNING_BATCH_SCHEMA_VERSION,
        "eligible_time_utc_ms": completeness.eligible_time_utc_ms,
        "completeness_snapshot_id": completeness.completeness_id,
        "completeness_snapshot_content_hash": completeness.completeness_content_hash,
        "ordered_entry_intent_ids": completeness.expected_entry_intent_ids,
        "ordered_resolution_refs": completeness.ordered_resolution_refs,
        "ordered_successful_sizing_result_ids": successful,
        "ordered_symbols": completeness.expected_symbols,
        "account_snapshot_id": account.snapshot_id,
        "account_snapshot_hash": account.snapshot_hash,
        "target_open_snapshot_ids": target_open_snapshot_ids,
        "batch_config_hash": batch_config_hash(),
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    batch_id, digest = formal_identity("pbatch_", payload)
    return PortfolioPlanningBatch(batch_id=batch_id, batch_content_hash=digest, **payload)
