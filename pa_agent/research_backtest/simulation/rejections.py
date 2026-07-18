from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pa_agent.research_backtest.domain.enums import RejectionDisposition, ResearchStage
from pa_agent.research_backtest.domain.rejections import ExecutionRejection
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent


class RejectionPolicyAction(StrEnum):
    CONTINUE = "CONTINUE"
    PATH_INVALID = "PATH_INVALID"
    EXPERIMENT_INVALID = "EXPERIMENT_INVALID"


@dataclass(frozen=True, slots=True)
class RejectionPolicyOutcome:
    action: RejectionPolicyAction
    rejections: tuple[ExecutionRejection, ...]
    controlling_rejection: ExecutionRejection | None
    stage: ResearchStage

    def path_invalid_event(self, event_time_utc_ms: int) -> PathInvalidEvent:
        rejection = self.controlling_rejection
        if self.action is RejectionPolicyAction.CONTINUE or rejection is None:
            raise ValueError("continuing rejection policy has no PathInvalidEvent")
        reason = (
            f"REJECTION_POLICY:{self.action.value}:{rejection.rejection_id}:"
            f"{rejection.reason.value}:{rejection.disposition.value}:{self.stage.value}"
        )
        return PathInvalidEvent(
            event_time_utc_ms,
            reason,
            rejection_id=rejection.rejection_id,
            rejection_reason=rejection.reason.value,
            rejection_disposition=rejection.disposition.value,
            rejection_stage=self.stage.value,
        )


def apply_rejection_policy(
    rejections: tuple[ExecutionRejection, ...],
    stage: ResearchStage,
) -> RejectionPolicyOutcome:
    if not isinstance(stage, ResearchStage):
        raise ValueError("rejection policy requires a formal ResearchStage")
    if any(not isinstance(item, ExecutionRejection) for item in rejections):
        raise TypeError("rejection policy accepts only formal ExecutionRejection objects")
    controlling: ExecutionRejection | None = None
    action = RejectionPolicyAction.CONTINUE
    for disposition, candidate_action in (
        (RejectionDisposition.EXPERIMENT_INVALID, RejectionPolicyAction.EXPERIMENT_INVALID),
        (RejectionDisposition.EXECUTION_PATH_INVALID, RejectionPolicyAction.PATH_INVALID),
        (RejectionDisposition.PLAN_CANCELLED, RejectionPolicyAction.PATH_INVALID),
    ):
        matches = tuple(item for item in rejections if item.disposition is disposition)
        if matches and (
            disposition is not RejectionDisposition.PLAN_CANCELLED
            or stage is ResearchStage.BACKTEST
        ):
            controlling = sorted(matches, key=lambda item: item.rejection_id)[0]
            action = candidate_action
            break
    return RejectionPolicyOutcome(action, rejections, controlling, stage)
