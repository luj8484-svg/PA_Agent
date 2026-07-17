from __future__ import annotations

from pa_agent.research_backtest.domain.base import formal_identity, require_commit, require_sha256
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    MarketView,
    ResearchStage,
    Side,
)
from pa_agent.research_backtest.domain.intents import EntryIntent
from pa_agent.research_backtest.domain.rejections import (
    ExecutionRejection,
    candidate_subject_ref,
    rejection_fact,
)
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.planning.time import entry_target_time, next_four_hour_anchor
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    ENTRY_INTENT_SCHEMA_VERSION,
)


def make_entry_intent(
    candidate: StrategyCandidate,
    config: ExecutionTimeConfig,
    *,
    computational_experiment_id: str,
    stage: ResearchStage,
    code_commit: str,
    dependency_lock_hash: str,
) -> EntryIntent | ExecutionRejection:
    if candidate.market_view is MarketView.NO_SETUP:
        return choose_rejection(
            subject=candidate_subject_ref(candidate),
            event_time_utc_ms=candidate.decision_time_utc_ms,
            facts=(rejection_fact(ExecutionRejectionReason.CANDIDATE_NOT_ACTIONABLE),),
            stage=stage,
            relevant_version_hashes=(
                ("indicator_config", candidate.indicator_config_hash),
                ("strategy_config", candidate.strategy_config_hash),
            ),
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    if candidate.market_view not in {MarketView.LONG, MarketView.SHORT}:
        raise ValueError("Candidate market view is invalid")
    require_sha256(computational_experiment_id, "computational_experiment_id")
    require_sha256(dependency_lock_hash, "dependency_lock_hash")
    require_commit(code_commit)
    side = Side(candidate.market_view.value)
    intent_config_hash = canonical_sha256(
        {
            "execution_time_config_id": config.config_id,
            "execution_time_config_content_hash": config.config_content_hash,
            "entry_intent_schema_version": ENTRY_INTENT_SCHEMA_VERSION,
            "canonical_version": CANONICAL_2B_VERSION,
        }
    )
    payload = {
        "schema_version": ENTRY_INTENT_SCHEMA_VERSION,
        "candidate_id": candidate.candidate_id,
        "candidate_schema_version": candidate.schema_version,
        "computational_experiment_id": computational_experiment_id,
        "symbol": candidate.symbol,
        "side": side,
        "candidate_decision_time_utc_ms": candidate.decision_time_utc_ms,
        "intent_created_time_utc_ms": candidate.decision_time_utc_ms,
        "execution_anchor_utc_ms": next_four_hour_anchor(candidate.decision_time_utc_ms),
        "target_execution_time_utc_ms": entry_target_time(candidate.decision_time_utc_ms, config),
        "execution_delay_minutes": config.entry_delay_minutes,
        "execution_time_config_id": config.config_id,
        "execution_time_config_content_hash": config.config_content_hash,
        "execution_time_config_version": config.version,
        "decision_visible_input_hash": candidate.decision_visible_input_hash,
        "strategy_version": candidate.strategy_version,
        "intent_config_hash": intent_config_hash,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    intent_id, digest = formal_identity("eint_", payload)
    return EntryIntent(intent_id=intent_id, intent_content_hash=digest, **payload)
