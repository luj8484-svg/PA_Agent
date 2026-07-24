from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.planning.time import MINUTE_MS, entry_target_time
from pa_agent.research_backtest.versions import MAX_HOLD_VERSION

EXECUTION_HORIZON_GATE_VERSION = "V2A_EXECUTION_HORIZON_GATE_V1"
FROZEN_MAXIMUM_HOLDING_MINUTES = 48 * 60
REJECT_INSUFFICIENT_EXECUTION_HORIZON = "REJECT_INSUFFICIENT_EXECUTION_HORIZON"


@dataclass(frozen=True, slots=True)
class ExecutionHorizonDecision:
    candidate_id: str
    latest_required_time_utc_ms: int
    split_end_exit_open_utc_ms: int
    outcome: str
    overrun_ms: int
    gate_version: str
    max_hold_version: str


@dataclass(frozen=True, slots=True)
class ExecutionHorizonGateResult:
    accepted_candidates: tuple[StrategyCandidate, ...]
    rejected_candidate_ids: tuple[str, ...]
    decisions: tuple[ExecutionHorizonDecision, ...]


def latest_required_execution_evidence_time(
    *,
    candidate: StrategyCandidate,
    execution_time_config: ExecutionTimeConfig,
    maximum_holding_minutes: int,
) -> int:
    if not isinstance(candidate, StrategyCandidate):
        raise TypeError("candidate must be a StrategyCandidate")
    if not isinstance(execution_time_config, ExecutionTimeConfig):
        raise TypeError("execution_time_config must be an ExecutionTimeConfig")
    if type(maximum_holding_minutes) is not int or maximum_holding_minutes <= 0:
        raise ValueError("maximum_holding_minutes must be a positive integer")
    entry_time = entry_target_time(candidate.decision_time_utc_ms, execution_time_config)
    maximum_exit_time = entry_time + maximum_holding_minutes * MINUTE_MS
    time_exit_execution_anchor = maximum_exit_time // MINUTE_MS * MINUTE_MS + MINUTE_MS
    return time_exit_execution_anchor + execution_time_config.exit_delay_minutes * MINUTE_MS


def is_execution_horizon_eligible(
    *,
    latest_required_time_utc_ms: int,
    split_end_exit_open_utc_ms: int,
) -> bool:
    if type(latest_required_time_utc_ms) is not int or latest_required_time_utc_ms < 0:
        raise ValueError("latest_required_time_utc_ms must be a nonnegative integer")
    if type(split_end_exit_open_utc_ms) is not int or split_end_exit_open_utc_ms < 0:
        raise ValueError("split_end_exit_open_utc_ms must be a nonnegative integer")
    return latest_required_time_utc_ms <= split_end_exit_open_utc_ms


def apply_execution_horizon_gate(
    *,
    candidates: tuple[StrategyCandidate, ...],
    execution_time_config: ExecutionTimeConfig,
    maximum_holding_minutes: int,
    split_end_exit_open_utc_ms: int,
) -> ExecutionHorizonGateResult:
    accepted: list[StrategyCandidate] = []
    rejected: list[str] = []
    decisions: list[ExecutionHorizonDecision] = []
    for candidate in candidates:
        latest = latest_required_execution_evidence_time(
            candidate=candidate,
            execution_time_config=execution_time_config,
            maximum_holding_minutes=maximum_holding_minutes,
        )
        eligible = is_execution_horizon_eligible(
            latest_required_time_utc_ms=latest,
            split_end_exit_open_utc_ms=split_end_exit_open_utc_ms,
        )
        outcome = "ACCEPT" if eligible else REJECT_INSUFFICIENT_EXECUTION_HORIZON
        decisions.append(
            ExecutionHorizonDecision(
                candidate_id=candidate.candidate_id,
                latest_required_time_utc_ms=latest,
                split_end_exit_open_utc_ms=split_end_exit_open_utc_ms,
                outcome=outcome,
                overrun_ms=max(0, latest - split_end_exit_open_utc_ms),
                gate_version=EXECUTION_HORIZON_GATE_VERSION,
                max_hold_version=MAX_HOLD_VERSION,
            )
        )
        if eligible:
            accepted.append(candidate)
        else:
            rejected.append(candidate.candidate_id)
    return ExecutionHorizonGateResult(
        accepted_candidates=tuple(accepted),
        rejected_candidate_ids=tuple(rejected),
        decisions=tuple(decisions),
    )
