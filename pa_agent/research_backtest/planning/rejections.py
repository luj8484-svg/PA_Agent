from __future__ import annotations

from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, ResearchStage
from pa_agent.research_backtest.domain.rejections import (
    REASON_PRIORITY,
    REJECTION_CONFIG_HASH,
    ExecutionRejection,
    RejectionFact,
    RejectionSubjectRef,
    disposition_for,
    rejection_identity,
    subject_kind,
)
from pa_agent.research_backtest.versions import EXECUTION_REJECTION_SCHEMA_VERSION


def choose_rejection(
    *,
    subject: RejectionSubjectRef,
    event_time_utc_ms: int,
    facts: tuple[RejectionFact, ...],
    stage: ResearchStage,
    relevant_version_hashes: tuple[tuple[str, str], ...],
    code_commit: str,
    dependency_lock_hash: str,
) -> ExecutionRejection:
    if not facts:
        raise ValueError("at least one rejection fact is required")
    selected = min((fact.reason for fact in facts), key=REASON_PRIORITY.__getitem__)
    disposition, retry_allowed = disposition_for(subject_kind(subject), selected, stage)
    if (
        disposition.value == "EXPERIMENT_INVALID"
        and selected is not ExecutionRejectionReason.DATA_INVALID
    ):
        legal_live_path_failure = (
            subject_kind(subject).value in {"ENTRY_INTENT", "EXIT_INTENT"}
            and stage is ResearchStage.LIVE_ELIGIBILITY_RESEARCH
            and selected
            in {
                ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
                ExecutionRejectionReason.CONTRACT_RULE_EXPIRED,
                ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
                ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED,
                ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE,
                ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
                ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
                ExecutionRejectionReason.OPEN_RISK_MODEL_UNAVAILABLE,
                ExecutionRejectionReason.BATCH_INCOMPLETE,
                ExecutionRejectionReason.POSITION_QUANTITY_RULE_MISMATCH,
            }
        )
        if not legal_live_path_failure:
            selected = ExecutionRejectionReason.DATA_INVALID
            disposition, retry_allowed = disposition_for(subject_kind(subject), selected, stage)
    required_values = tuple(
        sorted(
            {("research_stage", stage.value)}
            | {item for fact in facts for item in fact.required_values}
        )
    )
    observed_values = tuple(sorted({item for fact in facts for item in fact.observed_values}))
    gap_intervals = tuple(sorted({item for fact in facts for item in fact.gap_intervals}))
    payload = {
        "schema_version": EXECUTION_REJECTION_SCHEMA_VERSION,
        "subject": subject,
        "event_time_utc_ms": event_time_utc_ms,
        "reason": selected,
        "disposition": disposition,
        "retry_allowed": retry_allowed,
        "required_values": required_values,
        "observed_values": observed_values,
        "relevant_version_hashes": tuple(sorted(relevant_version_hashes)),
        "gap_intervals": gap_intervals,
        "rejection_config_hash": REJECTION_CONFIG_HASH,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    rejection_id, digest = rejection_identity(payload)
    return ExecutionRejection(
        rejection_id=rejection_id,
        rejection_content_hash=digest,
        **payload,
    )
