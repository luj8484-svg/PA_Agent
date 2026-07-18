from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import (
    AccountEvidenceRecords,
    AccountPlanningEvidenceBundle,
    AccountPlanningSnapshot,
    OpenRiskEvidence,
)
from pa_agent.research_backtest.domain.base import require_sha256
from pa_agent.research_backtest.domain.batches import (
    PortfolioBatchCompletenessSnapshot,
    PortfolioPlanningBatch,
    expected_intent_ref,
    portfolio_batch_completeness_snapshot,
    portfolio_planning_batch,
    resolution_ref,
)
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.contracts import ContractRuleCoverage
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import (
    RejectionDisposition,
    ResearchStage,
    ResolutionKind,
    ScheduledExitReason,
    Side,
    TrendState,
)
from pa_agent.research_backtest.domain.funding import (
    FundingRiskConfigSnapshot,
    FundingScheduleSnapshot,
)
from pa_agent.research_backtest.domain.intents import EntryIntent, exit_condition_snapshot
from pa_agent.research_backtest.domain.market_inputs import (
    TargetEventWatermark,
    TargetMinuteOpenSnapshot,
)
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan
from pa_agent.research_backtest.domain.rejections import (
    ExecutionRejection,
    entry_intent_subject_ref,
)
from pa_agent.research_backtest.domain.scaling import (
    AcceptedScalingItem,
    PortfolioScalingResult,
    RejectedScalingItem,
)
from pa_agent.research_backtest.domain.sizing import PositionSizingResult
from pa_agent.research_backtest.planning.exits import make_exit_intent
from pa_agent.research_backtest.planning.factory import (
    EntryPlanningInputs,
    build_entry_execution_plan,
)
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.planning.portfolio import scale_portfolio
from pa_agent.research_backtest.planning.sizing import SizingInputs, position_sizing
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
from pa_agent.research_backtest.simulation.positions import (
    IsolatedPosition,
    exit_execution_position_snapshot,
)


@dataclass(frozen=True, slots=True)
class PlannerDependencies:
    entry_inputs_factory: Callable[[object, object, object], object] | None
    entry_planner: Callable[[object], object] | None
    exit_inputs_factory: Callable[[object, object, object], object] | None
    exit_planner: Callable[[object], object] | None
    catalog_id: str | None = None
    catalog_content_hash: str | None = None


def production_planner_dependencies(
    catalog: object,
    candidates: tuple[object, ...],
) -> PlannerDependencies:
    from pa_agent.research_backtest.planning.exits import build_exit_execution_plan
    from pa_agent.research_backtest.simulation.evidence import (
        PlanningEvidenceFromEngine,
        build_entry_batch_inputs_from_engine,
        build_exit_inputs_from_engine,
    )

    def entry_inputs_factory(state, due, evidence):
        if not isinstance(evidence, PlanningEvidenceFromEngine):
            raise TypeError("production entry planning requires engine evidence bridge")
        return build_entry_batch_inputs_from_engine(
            state=state,
            due_intents=due,
            minute=evidence.minute,
            candidates=candidates,
            catalog=catalog,
        )

    def exit_inputs_factory(state, intent, evidence):
        if not isinstance(evidence, PlanningEvidenceFromEngine):
            raise TypeError("production exit planning requires engine evidence bridge")
        return build_exit_inputs_from_engine(state=state, intent=intent, evidence=evidence)

    return PlannerDependencies(
        entry_inputs_factory,
        build_entry_batch_planning_outcome,
        exit_inputs_factory,
        build_exit_execution_plan,
        catalog.catalog_id,
        catalog.catalog_content_hash,
    )


@dataclass(frozen=True, slots=True)
class EntryBatchItemEvidence:
    candidate: StrategyCandidate
    intent: EntryIntent
    target_open: TargetMinuteOpenSnapshot
    watermark: TargetEventWatermark
    contract: ContractRuleCoverage
    cost: CostModelSnapshot
    funding_schedule: FundingScheduleSnapshot
    funding_risk: FundingRiskConfigSnapshot
    funding_event_upper_bound: int


@dataclass(frozen=True, slots=True)
class EntryBatchPlanningInputs:
    items: tuple[EntryBatchItemEvidence, ...]
    account: AccountPlanningSnapshot
    account_evidence_bundle: AccountPlanningEvidenceBundle
    account_evidence_records: AccountEvidenceRecords
    open_risk_evidence_records: tuple[OpenRiskEvidence, ...]
    stage: ResearchStage
    split_start_utc_ms: int
    split_end_utc_ms: int
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("entry batch must contain at least one item")
        ordered = tuple(
            sorted(self.items, key=lambda item: (item.intent.symbol, item.intent.intent_id))
        )
        if len({item.intent.intent_id for item in ordered}) != len(ordered):
            raise ValueError("entry batch Intent IDs must be unique")
        if len({item.intent.symbol for item in ordered}) != len(ordered):
            raise ValueError("entry batch symbols must be unique")
        target_times = {item.intent.target_execution_time_utc_ms for item in ordered}
        if target_times != {self.account.event_time_utc_ms}:
            raise ValueError("entry batch must share the account target minute")


@dataclass(frozen=True, slots=True)
class EntryBatchPlanningOutcome:
    sizing_results: tuple[PositionSizingResult, ...]
    execution_rejections: tuple[ExecutionRejection, ...]
    completeness: PortfolioBatchCompletenessSnapshot
    batch: PortfolioPlanningBatch
    scaling: PortfolioScalingResult | ExecutionRejection | None
    rejected_scaling_items: tuple[RejectedScalingItem, ...]
    plan_inputs: tuple[EntryPlanningInputs, ...]
    plans: tuple[EntryExecutionPlan, ...]

    @property
    def audit_objects(self) -> tuple[object, ...]:
        scaling = (self.scaling,) if isinstance(self.scaling, PortfolioScalingResult) else ()
        return (
            *self.sizing_results,
            *self.execution_rejections,
            self.completeness,
            self.batch,
            *scaling,
            *self.rejected_scaling_items,
            *self.plans,
        )


class EntryBatchPostPlanInvariantError(ValueError):
    pass


def validate_entry_batch_post_plan(
    outcome: EntryBatchPlanningOutcome,
    *,
    available_balance: Decimal,
) -> None:
    plans = outcome.plans
    if not plans:
        return
    if not isinstance(outcome, EntryBatchPlanningOutcome):
        required_cash = sum((plan.required_cash for plan in plans), Decimal("0"))
        if required_cash > available_balance:
            raise EntryBatchPostPlanInvariantError("planned cash exceeds available balance")
        return
    if not isinstance(outcome.scaling, PortfolioScalingResult) or not outcome.plan_inputs:
        raise EntryBatchPostPlanInvariantError("plans require one formal scaling evidence chain")
    account = outcome.plan_inputs[0].account
    if any(item.account != account for item in outcome.plan_inputs):
        raise EntryBatchPostPlanInvariantError("plan inputs do not share one account snapshot")
    if account.available_balance - account.pending_plan_reserve != available_balance:
        raise EntryBatchPostPlanInvariantError(
            "account snapshot available balance does not match engine state"
        )
    if (
        len({plan.plan_id for plan in plans}) != len(plans)
        or len({plan.symbol for plan in plans}) != len(plans)
        or len({plan.accepted_scaling_item_id for plan in plans}) != len(plans)
    ):
        raise EntryBatchPostPlanInvariantError("entry batch plans must be unique")
    required_cash = sum((plan.required_cash for plan in plans), Decimal("0"))
    if required_cash > available_balance:
        raise EntryBatchPostPlanInvariantError("planned cash exceeds available balance")
    planned_risk = sum((plan.planned_risk for plan in plans), Decimal("0"))
    if (
        account.existing_open_risk + account.pending_plan_risk + planned_risk
        > account.current_equity * Decimal("0.01")
    ):
        raise EntryBatchPostPlanInvariantError("planned risk exceeds portfolio limit")
    accepted = {
        item.item_id: item
        for item in outcome.scaling.item_results
        if isinstance(item, AcceptedScalingItem)
    }
    for plan in plans:
        item = accepted.get(plan.accepted_scaling_item_id)
        if item is None:
            raise EntryBatchPostPlanInvariantError("plan does not reference an accepted item")
        if (
            plan.portfolio_planning_batch_id != outcome.batch.batch_id
            or plan.portfolio_planning_batch_content_hash != outcome.batch.batch_content_hash
            or plan.portfolio_scaling_result_id != outcome.scaling.result_id
            or plan.portfolio_scaling_result_content_hash != outcome.scaling.result_content_hash
            or plan.account_snapshot_id != account.snapshot_id
            or plan.account_snapshot_hash != account.snapshot_hash
            or plan.accepted_scaling_item_content_hash != item.item_content_hash
            or plan.symbol != item.symbol
            or plan.planned_risk != item.final_planned_risk
            or plan.required_cash != item.final_required_cash
        ):
            raise EntryBatchPostPlanInvariantError(
                "plan batch, scaling, account, risk, or cash evidence is inconsistent"
            )


def build_entry_batch_planning_outcome(
    inputs: EntryBatchPlanningInputs,
) -> EntryBatchPlanningOutcome:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
    ordered_items = tuple(
        sorted(inputs.items, key=lambda item: (item.intent.symbol, item.intent.intent_id))
    )
    sizing_results: list[PositionSizingResult] = []
    rejections: list[ExecutionRejection] = []
    resolutions = []
    item_by_sizing_id: dict[str, EntryBatchItemEvidence] = {}
    for item in ordered_items:
        sizing = position_sizing(
            SizingInputs(
                intent_id=item.intent.intent_id,
                target_execution_time_utc_ms=item.intent.target_execution_time_utc_ms,
                symbol=item.intent.symbol,
                side=item.intent.side,
                candidate=item.candidate,
                target_open=item.target_open,
                contract=item.contract,
                cost=item.cost,
                funding_risk=item.funding_risk,
                funding_event_upper_bound=item.funding_event_upper_bound,
                account=inputs.account,
                account_evidence_bundle=inputs.account_evidence_bundle,
                account_evidence_records=inputs.account_evidence_records,
                open_risk_evidence_records=inputs.open_risk_evidence_records,
                subject=entry_intent_subject_ref(item.intent),
                stage=inputs.stage,
                code_commit=inputs.code_commit,
                dependency_lock_hash=inputs.dependency_lock_hash,
            )
        )
        if isinstance(sizing, ExecutionRejection):
            rejections.append(sizing)
            resolution_kind = {
                RejectionDisposition.CANDIDATE_REJECTED: ResolutionKind.ECONOMIC_REJECTION,
                RejectionDisposition.EXECUTION_PATH_INVALID: ResolutionKind.EXECUTION_PATH_INVALID,
                RejectionDisposition.EXPERIMENT_INVALID: ResolutionKind.EXPERIMENT_INVALID,
            }.get(sizing.disposition, ResolutionKind.EXECUTION_PATH_INVALID)
            resolutions.append(
                resolution_ref(
                    item.intent.intent_id,
                    item.intent.symbol,
                    resolution_kind,
                    sizing.rejection_id,
                    sizing.rejection_content_hash,
                )
            )
        else:
            sizing_results.append(sizing)
            item_by_sizing_id[sizing.result_id] = item
            resolutions.append(
                resolution_ref(
                    item.intent.intent_id,
                    item.intent.symbol,
                    ResolutionKind.SIZING_RESULT,
                    sizing.result_id,
                    sizing.result_content_hash,
                )
            )
    target = inputs.account.event_time_utc_ms
    expected = tuple(
        expected_intent_ref(item.intent.intent_id, item.intent.symbol, target)
        for item in ordered_items
    )
    completeness = portfolio_batch_completeness_snapshot(
        expected,
        tuple(resolutions),
        completeness_event_time_utc_ms=target,
        source_event_id=f"entry-batch-complete:{target}",
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )
    ordered_sizings = tuple(sorted(sizing_results, key=lambda item: (item.symbol, item.result_id)))
    successful_items = tuple(item_by_sizing_id[item.result_id] for item in ordered_sizings)
    batch = portfolio_planning_batch(
        completeness,
        inputs.account,
        target_open_snapshot_ids=tuple(item.target_open.snapshot_id for item in successful_items),
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )
    if not ordered_sizings:
        return EntryBatchPlanningOutcome(
            (), tuple(rejections), completeness, batch, None, (), (), ()
        )
    scaling_item_rejections: list[ExecutionRejection] = []
    scaling = scale_portfolio(
        batch,
        inputs.account,
        ordered_sizings,
        {
            sizing.result_id: item_by_sizing_id[sizing.result_id].contract
            for sizing in ordered_sizings
        },
        tuple(item.target_open for item in successful_items),
        inputs.stage,
        rejection_audit=scaling_item_rejections,
    )
    rejections.extend(scaling_item_rejections)
    if isinstance(scaling, ExecutionRejection):
        return EntryBatchPlanningOutcome(
            ordered_sizings,
            tuple((*rejections, scaling)),
            completeness,
            batch,
            scaling,
            (),
            (),
            (),
        )
    rejected_items = tuple(
        item for item in scaling.item_results if isinstance(item, RejectedScalingItem)
    )
    accepted_by_sizing_id = {
        item.sizing_result_id: item
        for item in scaling.item_results
        if isinstance(item, AcceptedScalingItem)
    }
    plan_inputs: list[EntryPlanningInputs] = []
    plans: list[EntryExecutionPlan] = []
    for sizing in ordered_sizings:
        accepted = accepted_by_sizing_id.get(sizing.result_id)
        if accepted is None:
            continue
        item = item_by_sizing_id[sizing.result_id]
        plan_input = EntryPlanningInputs(
            candidate=item.candidate,
            intent=item.intent,
            target_open=item.target_open,
            watermark=item.watermark,
            contract=item.contract,
            cost=item.cost,
            funding_schedule=item.funding_schedule,
            funding_risk=item.funding_risk,
            account=inputs.account,
            account_evidence_bundle=inputs.account_evidence_bundle,
            account_evidence_records=inputs.account_evidence_records,
            open_risk_evidence_records=inputs.open_risk_evidence_records,
            stage=inputs.stage,
            completeness=completeness,
            batch=batch,
            sizing=sizing,
            scaling=scaling,
            accepted_item=accepted,
            split_start_utc_ms=inputs.split_start_utc_ms,
            split_end_utc_ms=inputs.split_end_utc_ms,
            code_commit=inputs.code_commit,
            dependency_lock_hash=inputs.dependency_lock_hash,
        )
        plan_inputs.append(plan_input)
        plan = build_entry_execution_plan(plan_input)
        if isinstance(plan, ExecutionRejection):
            rejections.append(plan)
        else:
            plans.append(plan)
    return EntryBatchPlanningOutcome(
        ordered_sizings,
        tuple(rejections),
        completeness,
        batch,
        scaling,
        rejected_items,
        tuple(plan_inputs),
        tuple(sorted(plans, key=lambda item: (item.symbol, item.plan_id))),
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
        position_hash = exit_execution_position_snapshot(position).snapshot_content_hash
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

    factory.exit_delay_minutes = execution_config.exit_delay_minutes  # type: ignore[attr-defined]
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
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
    due = _due(intents, minute_open_utc_ms)
    if not due:
        return ()
    if dependencies.entry_inputs_factory is None or dependencies.entry_planner is None:
        raise ValueError("entry planner dependencies are unavailable")
    return tuple(
        dependencies.entry_planner(dependencies.entry_inputs_factory(state, intent, evidence))
        for intent in due
    )


def plan_due_entry_batch(
    state: object,
    intents: tuple[object, ...],
    minute_open_utc_ms: int,
    evidence: object,
    dependencies: PlannerDependencies,
) -> object | None:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
    due = _due(intents, minute_open_utc_ms)
    if not due:
        return None
    if dependencies.entry_inputs_factory is None or dependencies.entry_planner is None:
        raise ValueError("entry batch planner dependencies are unavailable")
    batch_inputs = dependencies.entry_inputs_factory(state, due, evidence)
    return dependencies.entry_planner(batch_inputs)


def plan_due_exits(
    state: object,
    intents: tuple[object, ...],
    minute_open_utc_ms: int,
    evidence: object,
    dependencies: PlannerDependencies,
) -> tuple[object, ...]:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
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


def experiment_end_condition_time(
    simulation_end_exit_open_utc_ms: int, exit_delay_minutes: int = 0
) -> int:
    if simulation_end_exit_open_utc_ms <= 0 or simulation_end_exit_open_utc_ms % 60_000:
        raise ValueError("experiment end must be a positive UTC minute open")
    if type(exit_delay_minutes) is not int or exit_delay_minutes not in {0, 1, 2}:
        raise ValueError("exit delay must be 0, 1, or 2 minutes")
    condition_time = simulation_end_exit_open_utc_ms - exit_delay_minutes * 60_000 - 1
    if condition_time < 0:
        raise ValueError("experiment interval is too short for configured exit delay")
    return condition_time


def choose_scheduled_reason(
    reasons: tuple[ScheduledExitReason, ...],
) -> ScheduledExitReason:
    for reason in _REASON_PRIORITY:
        if reason in reasons:
            return reason
    raise ValueError("scheduled exit reason set is empty")


def merge_scheduled_reasons(
    *groups: tuple[ScheduledExitReason, ...],
) -> tuple[ScheduledExitReason, ...]:
    combined = {reason for group in groups for reason in group}
    return tuple(reason for reason in _REASON_PRIORITY if reason in combined)


def scheduled_exit_reasons(
    position: IsolatedPosition,
    event_time_utc_ms: int,
    trend_evidence: TrendEvidence | None,
    halted: bool,
    simulation_end_exit_open_utc_ms: int,
    exit_delay_minutes: int = 0,
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
    if event_time_utc_ms == experiment_end_condition_time(
        simulation_end_exit_open_utc_ms, exit_delay_minutes
    ):
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
