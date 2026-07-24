from __future__ import annotations

import inspect

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_v2a.execution_horizon import (
    FROZEN_MAXIMUM_HOLDING_MINUTES,
    REJECT_INSUFFICIENT_EXECUTION_HORIZON,
    apply_execution_horizon_gate,
    is_execution_horizon_eligible,
    latest_required_execution_evidence_time,
)
from tests.research_v2a.helpers import make_candidate

DECISION_TIME = 14_400_000 - 1


def _candidate():
    return make_candidate(
        decision_time_utc_ms=DECISION_TIME,
        strength="4",
    )


def test_complete_lifecycle_exactly_at_fold_end_is_eligible() -> None:
    candidate = _candidate()
    config = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    latest = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )

    assert is_execution_horizon_eligible(
        latest_required_time_utc_ms=latest,
        split_end_exit_open_utc_ms=latest,
    )


def test_complete_lifecycle_one_millisecond_after_fold_end_is_rejected() -> None:
    candidate = _candidate()
    config = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    latest = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )
    result = apply_execution_horizon_gate(
        candidates=(candidate,),
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
        split_end_exit_open_utc_ms=latest - 1,
    )

    assert result.accepted_candidates == ()
    assert result.rejected_candidate_ids == (candidate.candidate_id,)
    assert result.decisions[0].outcome == REJECT_INSUFFICIENT_EXECUTION_HORIZON
    assert result.decisions[0].overrun_ms == 1


def test_entry_delay_is_included() -> None:
    candidate = _candidate()
    zero = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=execution_time_config(
            entry_delay_minutes=0,
            exit_delay_minutes=1,
        ),
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )
    one = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=execution_time_config(
            entry_delay_minutes=1,
            exit_delay_minutes=1,
        ),
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )

    assert one - zero == 60_000


def test_frozen_48_hour_maximum_holding_is_included() -> None:
    candidate = _candidate()
    config = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    shorter = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES - 1,
    )
    frozen = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )

    assert frozen - shorter == 60_000


def test_exit_execution_delay_is_included() -> None:
    candidate = _candidate()
    zero = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=execution_time_config(
            entry_delay_minutes=1,
            exit_delay_minutes=0,
        ),
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )
    one = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=execution_time_config(
            entry_delay_minutes=1,
            exit_delay_minutes=1,
        ),
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )

    assert one - zero == 60_000


def test_gate_preserves_candidate_canonical_economic_fields() -> None:
    candidate = _candidate()
    before = canonical_sha256(candidate)
    config = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    latest = latest_required_execution_evidence_time(
        candidate=candidate,
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
    )
    result = apply_execution_horizon_gate(
        candidates=(candidate,),
        execution_time_config=config,
        maximum_holding_minutes=FROZEN_MAXIMUM_HOLDING_MINUTES,
        split_end_exit_open_utc_ms=latest,
    )

    assert result.accepted_candidates == (candidate,)
    assert result.accepted_candidates[0] is candidate
    assert canonical_sha256(result.accepted_candidates[0]) == before


def test_gate_inputs_are_decision_visible_only() -> None:
    assert tuple(inspect.signature(latest_required_execution_evidence_time).parameters) == (
        "candidate",
        "execution_time_config",
        "maximum_holding_minutes",
    )
    assert tuple(inspect.signature(apply_execution_horizon_gate).parameters) == (
        "candidates",
        "execution_time_config",
        "maximum_holding_minutes",
        "split_end_exit_open_utc_ms",
    )
