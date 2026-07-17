from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pa_agent.research_backtest.domain.base import require_sha256
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.enums import (
    ResearchStage,
    ScheduledExitReason,
    Side,
    TrendState,
)
from pa_agent.research_backtest.domain.intents import exit_condition_snapshot
from pa_agent.research_backtest.planning.exits import make_exit_intent
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
from pa_agent.research_backtest.simulation.positions import IsolatedPosition


@dataclass(frozen=True, slots=True)
class PlannerDependencies:
    entry_inputs_factory: Callable[[object, object, object], object] | None
    entry_planner: Callable[[object], object] | None
    exit_inputs_factory: Callable[[object, object, object], object] | None
    exit_planner: Callable[[object], object] | None


def production_planner_dependencies(
    entry_inputs_factory: Callable[[object, object, object], object],
    exit_inputs_factory: Callable[[object, object, object], object],
) -> PlannerDependencies:
    from pa_agent.research_backtest.planning.exits import build_exit_execution_plan
    from pa_agent.research_backtest.planning.factory import build_entry_execution_plan

    return PlannerDependencies(
        entry_inputs_factory,
        build_entry_execution_plan,
        exit_inputs_factory,
        build_exit_execution_plan,
    )


def make_candidate_intent_factory(
    execution_config: ExecutionTimeConfig,
    *,
    computational_experiment_id: str,
    stage: ResearchStage,
    code_commit: str,
    dependency_lock_hash: str,
) -> Callable[[object], object]:
    def factory(candidate: object) -> object:
        return make_entry_intent(
            candidate,
            execution_config,
            computational_experiment_id=computational_experiment_id,
            stage=stage,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    return factory


def make_scheduled_exit_intent_factory(
    execution_config: ExecutionTimeConfig,
    *,
    computational_experiment_id: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> Callable[[IsolatedPosition, tuple[ScheduledExitReason, ...], int, object], object]:
    def factory(
        position: IsolatedPosition,
        matched_reasons: tuple[ScheduledExitReason, ...],
        event_time_utc_ms: int,
        state: object,
    ) -> object:
        del state
        selected_reason = choose_scheduled_reason(matched_reasons)
        position_hash = canonical_sha256(position)
        visible_hash = canonical_sha256(
            {
                "position_snapshot_hash": position_hash,
                "matched_reasons": matched_reasons,
                "selected_reason": selected_reason,
                "condition_time_utc_ms": event_time_utc_ms,
            }
        )
        condition = exit_condition_snapshot(
            origin_candidate_id=position.origin_candidate_id,
            position_id=position.position_id,
            position_snapshot_hash=position_hash,
            symbol=position.symbol,
            position_side=position.side,
            exit_quantity=position.quantity,
            scheduled_exit_reason=selected_reason,
            condition_time_utc_ms=event_time_utc_ms,
            condition_visible_input_hash=visible_hash,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
        return make_exit_intent(
            condition,
            execution_config,
            computational_experiment_id=computational_experiment_id,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )

    return factory


def _due(intents: tuple[object, ...], minute_open_utc_ms: int) -> tuple[object, ...]:
    return tuple(
        sorted(
            (
                intent
                for intent in intents
                if intent.target_execution_time_utc_ms == minute_open_utc_ms
            ),
            key=lambda intent: (intent.symbol, intent.intent_id),
        )
    )


def plan_due_entries(
    state: object,
    intents: tuple[object, ...],
    minute_open_utc_ms: int,
    evidence: object,
    dependencies: PlannerDependencies,
) -> tuple[object, ...]:
    due = _due(intents, minute_open_utc_ms)
    if not due:
        return ()
    if dependencies.entry_inputs_factory is None or dependencies.entry_planner is None:
        raise ValueError("entry planner dependencies are unavailable")
    return tuple(
        dependencies.entry_planner(dependencies.entry_inputs_factory(state, intent, evidence))
        for intent in due
    )


def plan_due_exits(
    state: object,
    intents: tuple[object, ...],
    minute_open_utc_ms: int,
    evidence: object,
    dependencies: PlannerDependencies,
) -> tuple[object, ...]:
    due = _due(intents, minute_open_utc_ms)
    if not due:
        return ()
    if dependencies.exit_inputs_factory is None or dependencies.exit_planner is None:
        raise ValueError("exit planner dependencies are unavailable")
    return tuple(
        dependencies.exit_planner(dependencies.exit_inputs_factory(state, intent, evidence))
        for intent in due
    )


@dataclass(frozen=True, slots=True)
class TrendEvidence:
    decision_time_utc_ms: int
    trend_state: TrendState
    is_closed: bool
    content_hash: str
    symbol: str = "BTCUSDT"

    def __post_init__(self) -> None:
        if type(self.decision_time_utc_ms) is not int or self.decision_time_utc_ms < 0:
            raise ValueError("invalid trend evidence time")
        if not isinstance(self.trend_state, TrendState):
            raise ValueError("invalid trend state")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported trend evidence symbol")
        if type(self.is_closed) is not bool:
            raise ValueError("trend evidence closed flag must be bool")
        require_sha256(self.content_hash, "trend evidence content_hash")


_REASON_PRIORITY = (
    ScheduledExitReason.HALT_EXIT,
    ScheduledExitReason.TREND_EXIT,
    ScheduledExitReason.TIME_EXIT,
    ScheduledExitReason.EXPERIMENT_END,
)


def experiment_end_condition_time(simulation_end_exit_open_utc_ms: int) -> int:
    if simulation_end_exit_open_utc_ms <= 0 or simulation_end_exit_open_utc_ms % 60_000:
        raise ValueError("experiment end must be a positive UTC minute open")
    return simulation_end_exit_open_utc_ms - 1


def choose_scheduled_reason(
    reasons: tuple[ScheduledExitReason, ...],
) -> ScheduledExitReason:
    for reason in _REASON_PRIORITY:
        if reason in reasons:
            return reason
    raise ValueError("scheduled exit reason set is empty")


def scheduled_exit_reasons(
    position: IsolatedPosition,
    event_time_utc_ms: int,
    trend_evidence: TrendEvidence | None,
    halted: bool,
    simulation_end_exit_open_utc_ms: int,
) -> tuple[ScheduledExitReason, ...]:
    reasons: set[ScheduledExitReason] = set()
    if halted:
        reasons.add(ScheduledExitReason.HALT_EXIT)
    if event_time_utc_ms == position.maximum_exit_time_utc_ms:
        reasons.add(ScheduledExitReason.TIME_EXIT)
    if trend_evidence is not None and trend_evidence.decision_time_utc_ms == event_time_utc_ms:
        if not trend_evidence.is_closed:
            raise ValueError("trend evidence must be closed before exit evaluation")
        if position.side is Side.LONG and trend_evidence.trend_state is not TrendState.BULL:
            reasons.add(ScheduledExitReason.TREND_EXIT)
        if position.side is Side.SHORT and trend_evidence.trend_state is not TrendState.BEAR:
            reasons.add(ScheduledExitReason.TREND_EXIT)
    if event_time_utc_ms == experiment_end_condition_time(simulation_end_exit_open_utc_ms):
        reasons.add(ScheduledExitReason.EXPERIMENT_END)
    return tuple(reason for reason in _REASON_PRIORITY if reason in reasons)


def discover_scheduled_exits(
    position: IsolatedPosition,
    *,
    event_time_utc_ms: int,
    trend_evidence: TrendEvidence | None,
    trend_evidence_expected: bool,
    halted: bool,
    simulation_end_exit_open_utc_ms: int,
) -> tuple[ScheduledExitReason, ...] | PathInvalidEvent:
    if trend_evidence_expected and trend_evidence is None:
        return PathInvalidEvent(event_time_utc_ms, "TREND_EVIDENCE_UNAVAILABLE")
    return scheduled_exit_reasons(
        position,
        event_time_utc_ms,
        trend_evidence,
        halted,
        simulation_end_exit_open_utc_ms,
    )
