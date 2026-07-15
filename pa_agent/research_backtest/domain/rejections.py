from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    RejectionDisposition,
    RejectionSubjectKind,
    ResearchStage,
)
from pa_agent.research_backtest.domain.intents import EntryIntent, ExitIntent
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    EXECUTION_REJECTION_SCHEMA_VERSION,
    REJECTION_PRIORITY_VERSION,
    REJECTION_SUBJECT_DISPOSITION_VERSION,
    REJECTION_SUBJECT_REF_SCHEMA_VERSION,
)

SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})

REASON_PRIORITY = {
    reason: rank
    for rank, reason in enumerate(
        (
            ExecutionRejectionReason.DATA_INVALID,
            ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
            ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
            ExecutionRejectionReason.OPEN_RISK_MODEL_UNAVAILABLE,
            ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
            ExecutionRejectionReason.CONTRACT_RULE_EXPIRED,
            ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
            ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED,
            ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE,
            ExecutionRejectionReason.BATCH_INCOMPLETE,
            ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED,
            ExecutionRejectionReason.POSITION_QUANTITY_RULE_MISMATCH,
            ExecutionRejectionReason.EXPERIMENT_HALTED,
            ExecutionRejectionReason.EXISTING_POSITION,
            ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT,
            ExecutionRejectionReason.GAP_TOO_LARGE,
            ExecutionRejectionReason.PRICE_GEOMETRY_INVALID,
            ExecutionRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE,
            ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO,
            ExecutionRejectionReason.BELOW_MIN_QTY,
            ExecutionRejectionReason.BELOW_MIN_NOTIONAL,
            ExecutionRejectionReason.CANDIDATE_NOT_ACTIONABLE,
        ),
        start=1,
    )
}


def _validate_subject(value: object, prefix: str = "sref_") -> None:
    if value.schema_version != REJECTION_SUBJECT_REF_SCHEMA_VERSION:
        raise ValueError("unsupported rejection subject schema")
    if value.symbols != tuple(sorted(set(value.symbols))) or not value.symbols:
        raise ValueError("subject symbols must be nonempty, unique, and sorted")
    if any(symbol not in SUPPORTED_SYMBOLS for symbol in value.symbols):
        raise ValueError("unsupported rejection subject symbol")
    if not value.origin_ids or any(
        not isinstance(item, str) or not item for item in value.origin_ids
    ):
        raise ValueError("subject origin IDs must be nonempty")
    verify_formal_identity(
        value,
        id_field="subject_id",
        hash_field="subject_content_hash",
        prefix=prefix,
    )


@dataclass(frozen=True, slots=True)
class CandidateSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    candidate_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    decision_visible_input_hash: str

    def __post_init__(self) -> None:
        if len(self.symbols) != 1 or self.origin_ids != (self.candidate_id,):
            raise ValueError("Candidate subject cardinality is invalid")
        require_sha256(self.decision_visible_input_hash, "decision_visible_input_hash")
        _validate_subject(self)


@dataclass(frozen=True, slots=True)
class EntryIntentSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    entry_intent_id: str
    candidate_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    intent_content_hash: str

    def __post_init__(self) -> None:
        if len(self.symbols) != 1 or self.origin_ids != (self.candidate_id,):
            raise ValueError("EntryIntent subject cardinality is invalid")
        require_sha256(self.intent_content_hash, "intent_content_hash")
        _validate_subject(self)


@dataclass(frozen=True, slots=True)
class ExitIntentSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    exit_intent_id: str
    condition_event_id: str
    position_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    condition_visible_input_hash: str
    position_snapshot_hash: str

    def __post_init__(self) -> None:
        if len(self.symbols) != 1 or self.origin_ids != (self.condition_event_id, self.position_id):
            raise ValueError("ExitIntent subject cardinality is invalid")
        require_sha256(self.condition_visible_input_hash, "condition_visible_input_hash")
        require_sha256(self.position_snapshot_hash, "position_snapshot_hash")
        _validate_subject(self)


@dataclass(frozen=True, slots=True)
class EntryPlanSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    entry_plan_id: str
    entry_intent_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    plan_content_hash: str

    def __post_init__(self) -> None:
        if len(self.symbols) != 1 or len(self.origin_ids) != 2:
            raise ValueError("EntryPlan subject cardinality is invalid")
        require_sha256(self.plan_content_hash, "plan_content_hash")
        _validate_subject(self)


@dataclass(frozen=True, slots=True)
class ExitPlanSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    exit_plan_id: str
    exit_intent_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    plan_content_hash: str

    def __post_init__(self) -> None:
        if len(self.symbols) != 1 or len(self.origin_ids) != 3:
            raise ValueError("ExitPlan subject cardinality is invalid")
        require_sha256(self.plan_content_hash, "plan_content_hash")
        _validate_subject(self)


@dataclass(frozen=True, slots=True)
class PortfolioBatchSubjectRef:
    schema_version: str
    subject_id: str
    subject_content_hash: str
    portfolio_planning_batch_id: str
    symbols: tuple[str, ...]
    origin_ids: tuple[str, ...]
    batch_content_hash: str
    account_snapshot_hash: str
    target_open_snapshot_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonempty_string(self.portfolio_planning_batch_id, "portfolio_planning_batch_id")
        require_sha256(self.batch_content_hash, "batch_content_hash")
        require_sha256(self.account_snapshot_hash, "account_snapshot_hash")
        if len(self.target_open_snapshot_hashes) != len(self.symbols):
            raise ValueError("batch target-open hashes must match symbol cardinality")
        for value in self.target_open_snapshot_hashes:
            require_sha256(value, "target_open_snapshot_hash")
        _validate_subject(self)


RejectionSubjectRef: TypeAlias = (
    CandidateSubjectRef
    | EntryIntentSubjectRef
    | ExitIntentSubjectRef
    | EntryPlanSubjectRef
    | ExitPlanSubjectRef
    | PortfolioBatchSubjectRef
)


@dataclass(frozen=True, slots=True)
class RejectionFact:
    reason: ExecutionRejectionReason
    required_values: tuple[tuple[str, str], ...]
    observed_values: tuple[tuple[str, str], ...]
    gap_intervals: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reason, ExecutionRejectionReason):
            raise ValueError("rejection fact requires a frozen reason")
        for values in (self.required_values, self.observed_values):
            if values != tuple(sorted(values)):
                raise ValueError("rejection fact evidence must be sorted")
        if self.gap_intervals != tuple(sorted(self.gap_intervals)):
            raise ValueError("rejection fact gaps must be sorted")
        if any(
            type(start) is not int or type(end) is not int or start > end
            for start, end in self.gap_intervals
        ):
            raise ValueError("rejection fact gaps must be closed integer intervals")


@dataclass(frozen=True, slots=True)
class ExecutionRejection:
    schema_version: str
    rejection_id: str
    rejection_content_hash: str
    subject: RejectionSubjectRef
    event_time_utc_ms: int
    reason: ExecutionRejectionReason
    disposition: RejectionDisposition
    retry_allowed: bool
    required_values: tuple[tuple[str, str], ...]
    observed_values: tuple[tuple[str, str], ...]
    relevant_version_hashes: tuple[tuple[str, str], ...]
    gap_intervals: tuple[tuple[int, int], ...]
    rejection_config_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_REJECTION_SCHEMA_VERSION:
            raise ValueError("unsupported execution rejection schema")
        require_utc_ms(self.event_time_utc_ms, "rejection event time")
        if not isinstance(self.reason, ExecutionRejectionReason):
            raise ValueError("invalid execution rejection reason")
        if (
            not isinstance(self.disposition, RejectionDisposition)
            or type(self.retry_allowed) is not bool
        ):
            raise ValueError("invalid rejection disposition")
        for name in ("required_values", "observed_values", "relevant_version_hashes"):
            values = getattr(self, name)
            if values != tuple(sorted(values)):
                raise ValueError(f"{name} must be sorted")
        for _, digest in self.relevant_version_hashes:
            require_sha256(digest, "relevant version hash")
        if self.gap_intervals != tuple(sorted(self.gap_intervals)) or any(
            start > end for start, end in self.gap_intervals
        ):
            raise ValueError("rejection gap intervals must be sorted closed intervals")
        require_sha256(self.rejection_config_hash, "rejection_config_hash")
        if self.rejection_config_hash != REJECTION_CONFIG_HASH:
            raise ValueError("rejection config hash does not match frozen matrix")
        stage_values = [value for key, value in self.required_values if key == "research_stage"]
        if len(stage_values) != 1:
            raise ValueError("rejection evidence must contain exactly one research stage")
        expected = disposition_for(
            subject_kind(self.subject), self.reason, ResearchStage(stage_values[0])
        )
        if (self.disposition, self.retry_allowed) != expected:
            raise ValueError("rejection disposition contradicts subject/reason/stage matrix")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="rejection_id",
            hash_field="rejection_content_hash",
            prefix="rej_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def subject_kind(subject: RejectionSubjectRef) -> RejectionSubjectKind:
    if isinstance(subject, CandidateSubjectRef):
        return RejectionSubjectKind.CANDIDATE
    if isinstance(subject, EntryIntentSubjectRef):
        return RejectionSubjectKind.ENTRY_INTENT
    if isinstance(subject, ExitIntentSubjectRef):
        return RejectionSubjectKind.EXIT_INTENT
    if isinstance(subject, EntryPlanSubjectRef):
        return RejectionSubjectKind.ENTRY_PLAN
    if isinstance(subject, ExitPlanSubjectRef):
        return RejectionSubjectKind.EXIT_PLAN
    if isinstance(subject, PortfolioBatchSubjectRef):
        return RejectionSubjectKind.PORTFOLIO_BATCH
    raise TypeError("unsupported rejection subject")


PATH_REASONS = frozenset(
    {
        ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
        ExecutionRejectionReason.CONTRACT_RULE_EXPIRED,
        ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
        ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED,
        ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE,
        ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
        ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
        ExecutionRejectionReason.OPEN_RISK_MODEL_UNAVAILABLE,
        ExecutionRejectionReason.BATCH_INCOMPLETE,
    }
)
NONRETRY_ENTRY_ECONOMIC = frozenset(
    {
        ExecutionRejectionReason.GAP_TOO_LARGE,
        ExecutionRejectionReason.PRICE_GEOMETRY_INVALID,
        ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO,
        ExecutionRejectionReason.BELOW_MIN_QTY,
        ExecutionRejectionReason.BELOW_MIN_NOTIONAL,
    }
)


def disposition_for(
    kind: RejectionSubjectKind,
    reason: ExecutionRejectionReason,
    stage: ResearchStage,
) -> tuple[RejectionDisposition, bool]:
    if reason is ExecutionRejectionReason.DATA_INVALID:
        return RejectionDisposition.EXPERIMENT_INVALID, False
    if kind is RejectionSubjectKind.CANDIDATE:
        if reason is ExecutionRejectionReason.CANDIDATE_NOT_ACTIONABLE:
            return RejectionDisposition.CANDIDATE_REJECTED, False
    elif kind is RejectionSubjectKind.ENTRY_INTENT:
        if reason is ExecutionRejectionReason.EXPERIMENT_HALTED:
            return RejectionDisposition.CANDIDATE_REJECTED, stage is ResearchStage.PAPER_SIMULATION
        if reason in {
            ExecutionRejectionReason.EXISTING_POSITION,
            ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT,
            ExecutionRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE,
        }:
            return RejectionDisposition.CANDIDATE_REJECTED, True
        if reason in NONRETRY_ENTRY_ECONOMIC:
            return RejectionDisposition.CANDIDATE_REJECTED, False
        if reason in PATH_REASONS:
            if stage is ResearchStage.LIVE_ELIGIBILITY_RESEARCH:
                return RejectionDisposition.EXPERIMENT_INVALID, False
            return (
                RejectionDisposition.EXECUTION_PATH_INVALID,
                stage is ResearchStage.PAPER_SIMULATION,
            )
    elif kind is RejectionSubjectKind.PORTFOLIO_BATCH:
        if reason in {
            ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT,
            ExecutionRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE,
        }:
            return RejectionDisposition.CANDIDATE_REJECTED, True
        if reason in {
            ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO,
            ExecutionRejectionReason.BELOW_MIN_QTY,
            ExecutionRejectionReason.BELOW_MIN_NOTIONAL,
        }:
            return RejectionDisposition.CANDIDATE_REJECTED, False
    elif kind is RejectionSubjectKind.EXIT_INTENT:
        if reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED:
            return RejectionDisposition.PLAN_CANCELLED, True
        if reason in {
            ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
            ExecutionRejectionReason.CONTRACT_RULE_EXPIRED,
            ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
            ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
            ExecutionRejectionReason.POSITION_QUANTITY_RULE_MISMATCH,
        }:
            if stage is ResearchStage.BACKTEST:
                return RejectionDisposition.EXECUTION_PATH_INVALID, False
            if stage is ResearchStage.PAPER_SIMULATION:
                return RejectionDisposition.PLAN_CANCELLED, True
            return RejectionDisposition.EXPERIMENT_INVALID, False
    elif (
        kind is RejectionSubjectKind.EXIT_PLAN
        and reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED
    ):
        return RejectionDisposition.PLAN_CANCELLED, stage is ResearchStage.PAPER_SIMULATION
    return RejectionDisposition.EXPERIMENT_INVALID, False


DISPOSITION_ROWS = tuple(
    sorted(
        (
            kind.value,
            reason.value,
            stage.value,
            disposition_for(kind, reason, stage)[0].value,
            str(disposition_for(kind, reason, stage)[1]).lower(),
        )
        for kind in RejectionSubjectKind
        for reason in ExecutionRejectionReason
        for stage in ResearchStage
    )
)
REJECTION_CONFIG_HASH = canonical_sha256(
    {
        "rejection_schema_version": EXECUTION_REJECTION_SCHEMA_VERSION,
        "subject_union_schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "ordered_reason_priority_rows": tuple(
            (reason.value, REASON_PRIORITY[reason])
            for reason in sorted(REASON_PRIORITY, key=REASON_PRIORITY.get)
        ),
        "ordered_subject_reason_stage_disposition_retry_rows": DISPOSITION_ROWS,
        "rejection_priority_version": REJECTION_PRIORITY_VERSION,
        "subject_disposition_version": REJECTION_SUBJECT_DISPOSITION_VERSION,
        "canonical_version": CANONICAL_2B_VERSION,
    }
)


def _subject(payload: dict[str, object], cls: type[RejectionSubjectRef]) -> RejectionSubjectRef:
    subject_id, digest = formal_identity("sref_", payload)
    return cls(subject_id=subject_id, subject_content_hash=digest, **payload)


def candidate_subject_ref(candidate: StrategyCandidate) -> CandidateSubjectRef:
    payload = {
        "schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "candidate_id": candidate.candidate_id,
        "symbols": (candidate.symbol,),
        "origin_ids": (candidate.candidate_id,),
        "decision_visible_input_hash": candidate.decision_visible_input_hash,
    }
    return _subject(payload, CandidateSubjectRef)


def entry_intent_subject_ref(intent: EntryIntent) -> EntryIntentSubjectRef:
    payload = {
        "schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "entry_intent_id": intent.intent_id,
        "candidate_id": intent.candidate_id,
        "symbols": (intent.symbol,),
        "origin_ids": (intent.candidate_id,),
        "intent_content_hash": intent.intent_content_hash,
    }
    return _subject(payload, EntryIntentSubjectRef)


def entry_intent_subject_ref_from_identity(
    *,
    entry_intent_id: str,
    candidate_id: str,
    symbol: str,
    intent_content_hash: str,
) -> EntryIntentSubjectRef:
    """Build the same closed subject reference when only frozen Intent identity is available."""
    payload = {
        "schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "entry_intent_id": entry_intent_id,
        "candidate_id": candidate_id,
        "symbols": (symbol,),
        "origin_ids": (candidate_id,),
        "intent_content_hash": intent_content_hash,
    }
    return _subject(payload, EntryIntentSubjectRef)


def exit_intent_subject_ref(intent: ExitIntent) -> ExitIntentSubjectRef:
    payload = {
        "schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "exit_intent_id": intent.intent_id,
        "condition_event_id": intent.condition_event_id,
        "position_id": intent.position_id,
        "symbols": (intent.symbol,),
        "origin_ids": (intent.condition_event_id, intent.position_id),
        "condition_visible_input_hash": intent.condition_visible_input_hash,
        "position_snapshot_hash": intent.position_snapshot_hash,
    }
    return _subject(payload, ExitIntentSubjectRef)


def portfolio_batch_subject_ref(
    *,
    portfolio_planning_batch_id: str,
    symbols: tuple[str, ...],
    ordered_entry_intent_ids: tuple[str, ...],
    batch_content_hash: str,
    account_snapshot_hash: str,
    target_open_snapshot_hashes: tuple[str, ...],
) -> PortfolioBatchSubjectRef:
    payload = {
        "schema_version": REJECTION_SUBJECT_REF_SCHEMA_VERSION,
        "portfolio_planning_batch_id": portfolio_planning_batch_id,
        "symbols": tuple(sorted(set(symbols))),
        "origin_ids": ordered_entry_intent_ids,
        "batch_content_hash": batch_content_hash,
        "account_snapshot_hash": account_snapshot_hash,
        "target_open_snapshot_hashes": target_open_snapshot_hashes,
    }
    return _subject(payload, PortfolioBatchSubjectRef)


def rejection_fact(
    reason: str | ExecutionRejectionReason,
    *,
    required_values: tuple[tuple[str, str], ...] = (),
    observed_values: tuple[tuple[str, str], ...] = (),
    gap_intervals: tuple[tuple[int, int], ...] = (),
) -> RejectionFact:
    return RejectionFact(
        ExecutionRejectionReason(reason),
        tuple(sorted(required_values)),
        tuple(sorted(observed_values)),
        tuple(sorted(gap_intervals)),
    )


def rejection_identity(payload: dict[str, object]) -> tuple[str, str]:
    return formal_identity("rej_", payload)
