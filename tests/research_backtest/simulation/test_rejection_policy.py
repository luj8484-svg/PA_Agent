import pytest

from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    RejectionDisposition,
    ResearchStage,
)
from pa_agent.research_backtest.domain.rejections import entry_intent_subject_ref
from tests.research_backtest.execution.unit.test_rejection_matrix import intent, reject


@pytest.mark.parametrize(
    "reason",
    (
        ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
        ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
        ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED,
    ),
)
def test_execution_path_invalid_rejections_fail_path(reason) -> None:
    from pa_agent.research_backtest.simulation.rejections import (
        RejectionPolicyAction,
        apply_rejection_policy,
    )

    rejection = reject(entry_intent_subject_ref(intent()), (reason,))
    assert rejection.disposition is RejectionDisposition.EXECUTION_PATH_INVALID
    outcome = apply_rejection_policy((rejection,), ResearchStage.BACKTEST)
    assert outcome.action is RejectionPolicyAction.PATH_INVALID
    invalid = outcome.path_invalid_event(rejection.event_time_utc_ms)
    assert invalid.rejection_id == rejection.rejection_id
    assert invalid.rejection_reason == rejection.reason.value
    assert invalid.rejection_disposition == rejection.disposition.value


def test_data_invalid_rejection_invalidates_experiment() -> None:
    from pa_agent.research_backtest.simulation.rejections import (
        RejectionPolicyAction,
        apply_rejection_policy,
    )

    rejection = reject(
        entry_intent_subject_ref(intent()),
        (ExecutionRejectionReason.DATA_INVALID,),
    )
    outcome = apply_rejection_policy((rejection,), ResearchStage.BACKTEST)
    assert rejection.disposition is RejectionDisposition.EXPERIMENT_INVALID
    assert outcome.action is RejectionPolicyAction.EXPERIMENT_INVALID


def test_below_minimum_candidate_rejection_allows_path_to_continue() -> None:
    from pa_agent.research_backtest.simulation.rejections import (
        RejectionPolicyAction,
        apply_rejection_policy,
    )

    rejection = reject(
        entry_intent_subject_ref(intent()),
        (ExecutionRejectionReason.BELOW_MIN_QTY,),
    )
    outcome = apply_rejection_policy((rejection,), ResearchStage.BACKTEST)
    assert rejection.disposition is RejectionDisposition.CANDIDATE_REJECTED
    assert outcome.action is RejectionPolicyAction.CONTINUE
    assert outcome.rejections == (rejection,)


def test_invalid_disposition_dominates_accepted_peer_batch() -> None:
    from pa_agent.research_backtest.simulation.rejections import (
        RejectionPolicyAction,
        apply_rejection_policy,
    )

    path_invalid = reject(
        entry_intent_subject_ref(intent()),
        (ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,),
    )
    candidate_only = reject(
        entry_intent_subject_ref(intent()),
        (ExecutionRejectionReason.BELOW_MIN_QTY,),
    )
    outcome = apply_rejection_policy((candidate_only, path_invalid), ResearchStage.BACKTEST)
    assert outcome.action is RejectionPolicyAction.PATH_INVALID
    assert outcome.rejections == (candidate_only, path_invalid)
