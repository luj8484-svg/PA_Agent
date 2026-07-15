from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import (
    AccountEvidenceRecords,
    AccountPlanningEvidenceBundle,
    AccountPlanningSnapshot,
    RequiredAccountEvidenceUnavailableError,
    make_account_planning_snapshot,
)
from pa_agent.research_backtest.domain.batches import (
    PortfolioBatchCompletenessSnapshot,
    PortfolioPlanningBatch,
)
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.contracts import (
    ApproximatedContractRuleCoverage,
    ContractRuleCoverage,
    ContractRuleExpiredError,
    ContractRuleUnavailableError,
    UnavailableContractRuleCoverage,
    ensure_contract_usable,
)
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import (
    ContractRuleMode,
    ExecutionRejectionReason,
    ExperimentState,
    MarginMode,
    OrderType,
    PositionMode,
    ResearchStage,
    TriggerBasis,
)
from pa_agent.research_backtest.domain.funding import (
    CoveredFundingRiskConfigSnapshot,
    FundingRiskConfigSnapshot,
    FundingScheduleSnapshot,
    FundingScheduleUnverifiedError,
)
from pa_agent.research_backtest.domain.intents import EntryIntent
from pa_agent.research_backtest.domain.market_inputs import (
    TargetEventWatermark,
    TargetMinuteOpenSnapshot,
)
from pa_agent.research_backtest.domain.plans import (
    EntryExecutionPlan,
    entry_execution_plan,
    plan_config_hash,
)
from pa_agent.research_backtest.domain.rejections import (
    ExecutionRejection,
    entry_intent_subject_ref,
    rejection_fact,
)
from pa_agent.research_backtest.domain.scaling import (
    AcceptedScalingItem,
    PortfolioScalingResult,
)
from pa_agent.research_backtest.domain.sizing import PositionSizingResult
from pa_agent.research_backtest.planning.costs import entry_fee, exit_fee_reserve
from pa_agent.research_backtest.planning.funding import (
    count_funding_events,
    effective_adverse_rate_cap,
    funding_reserve,
)
from pa_agent.research_backtest.planning.prices import adverse_gap
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.versions import ENTRY_EXECUTION_PLAN_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class EntryPlanningInputs:
    candidate: StrategyCandidate
    intent: EntryIntent
    target_open: TargetMinuteOpenSnapshot | None
    watermark: TargetEventWatermark
    contract: ContractRuleCoverage
    cost: CostModelSnapshot | None
    funding_schedule: FundingScheduleSnapshot
    funding_risk: FundingRiskConfigSnapshot
    account: AccountPlanningSnapshot | None
    account_evidence_bundle: AccountPlanningEvidenceBundle | None
    account_evidence_records: AccountEvidenceRecords | None
    stage: ResearchStage
    completeness: PortfolioBatchCompletenessSnapshot
    batch: PortfolioPlanningBatch
    sizing: PositionSizingResult
    scaling: PortfolioScalingResult
    accepted_item: AcceptedScalingItem
    split_start_utc_ms: int
    split_end_utc_ms: int
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ResearchStage):
            raise ValueError("invalid entry-planning research stage")


def _reject(inputs: EntryPlanningInputs, reason: ExecutionRejectionReason) -> ExecutionRejection:
    version_hashes = [("batch", inputs.batch.batch_content_hash)]
    if inputs.account is not None:
        version_hashes.append(("account", inputs.account.snapshot_hash))
    if inputs.account_evidence_bundle is not None:
        version_hashes.append(
            ("account_evidence", inputs.account_evidence_bundle.bundle_content_hash)
        )
    return choose_rejection(
        subject=entry_intent_subject_ref(inputs.intent),
        event_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        facts=(rejection_fact(reason),),
        stage=inputs.stage,
        relevant_version_hashes=tuple(sorted(version_hashes)),
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )


def _validate_chain(inputs: EntryPlanningInputs) -> None:
    candidate = inputs.candidate
    intent = inputs.intent
    target = intent.target_execution_time_utc_ms
    if inputs.target_open is None or inputs.account is None:
        raise ValueError("required entry planning evidence is unavailable")
    if (
        intent.candidate_id != candidate.candidate_id
        or intent.symbol != candidate.symbol
        or intent.side.value != candidate.market_view.value
        or intent.candidate_decision_time_utc_ms != candidate.decision_time_utc_ms
        or intent.decision_visible_input_hash != candidate.decision_visible_input_hash
    ):
        raise ValueError("Candidate and EntryIntent evidence do not match")
    if not inputs.split_start_utc_ms <= candidate.decision_time_utc_ms < inputs.split_end_utc_ms:
        raise ValueError("Candidate is outside the experimental split")
    maximum_exit = target + 172_800_000
    if not inputs.split_start_utc_ms <= target < inputs.split_end_utc_ms:
        raise ValueError("entry target is outside the experimental split")
    if maximum_exit >= inputs.split_end_utc_ms:
        raise ValueError("maximum exit is outside the experimental split")
    if (
        inputs.target_open.symbol != intent.symbol
        or inputs.target_open.open_time_utc_ms != target
        or inputs.watermark.symbol != intent.symbol
        or inputs.watermark.target_open_time_utc_ms != target
        or inputs.watermark.event_watermark_time_utc_ms < target
    ):
        raise ValueError("target-open or watermark evidence does not match Intent")
    if isinstance(inputs.contract, UnavailableContractRuleCoverage):
        raise ValueError("contract rule is unavailable")
    if (
        inputs.contract.symbol != intent.symbol
        or inputs.contract.query_time_utc_ms != target
        or inputs.cost.symbol != intent.symbol
        or inputs.funding_schedule.symbol != intent.symbol
        or inputs.funding_risk.symbol != intent.symbol
    ):
        raise ValueError("planning evidence symbol does not match Intent")
    if not isinstance(inputs.funding_risk, CoveredFundingRiskConfigSnapshot):
        raise ValueError("funding risk config is unavailable")
    if not (
        inputs.funding_risk.effective_from_utc_ms
        <= target
        < inputs.funding_risk.effective_to_utc_ms
    ):
        raise ValueError("funding risk config does not cover target")
    if inputs.account.event_time_utc_ms != target:
        raise ValueError("account snapshot is not frozen at target time")
    if (
        inputs.completeness.eligible_time_utc_ms != target
        or inputs.batch.eligible_time_utc_ms != target
        or inputs.batch.completeness_snapshot_id != inputs.completeness.completeness_id
        or inputs.batch.completeness_snapshot_content_hash
        != inputs.completeness.completeness_content_hash
        or inputs.batch.account_snapshot_id != inputs.account.snapshot_id
        or inputs.batch.account_snapshot_hash != inputs.account.snapshot_hash
        or inputs.target_open.snapshot_id not in inputs.batch.target_open_snapshot_ids
        or intent.intent_id not in inputs.batch.ordered_entry_intent_ids
        or inputs.sizing.result_id not in inputs.batch.ordered_successful_sizing_result_ids
    ):
        raise ValueError("completeness or planning-batch evidence chain is invalid")
    if (
        inputs.sizing.intent_id != intent.intent_id
        or inputs.sizing.symbol != intent.symbol
        or inputs.sizing.side is not intent.side
        or inputs.sizing.reference_price != inputs.target_open.open_price
        or inputs.sizing.contract_rule_coverage_id != inputs.contract.coverage_id
        or inputs.sizing.cost_model_snapshot_id != inputs.cost.snapshot_id
        or inputs.sizing.funding_risk_config_id != inputs.funding_risk.config_id
        or inputs.sizing.account_snapshot_id != inputs.account.snapshot_id
        or inputs.sizing.account_snapshot_hash != inputs.account.snapshot_hash
    ):
        raise ValueError("position-sizing evidence chain is invalid")
    adverse_gap(
        intent.side,
        candidate.decision_close,
        inputs.target_open.open_price,
        candidate.atr14_4h,
    )
    if (
        inputs.scaling.portfolio_planning_batch_id != inputs.batch.batch_id
        or inputs.scaling.portfolio_planning_batch_content_hash != inputs.batch.batch_content_hash
        or inputs.scaling.account_snapshot_id != inputs.account.snapshot_id
        or inputs.scaling.account_snapshot_hash != inputs.account.snapshot_hash
        or inputs.scaling.ordered_input_result_ids
        != inputs.batch.ordered_successful_sizing_result_ids
        or inputs.accepted_item not in inputs.scaling.item_results
        or inputs.accepted_item.sizing_result_id != inputs.sizing.result_id
        or inputs.accepted_item.symbol != intent.symbol
    ):
        raise ValueError("scaling evidence chain is invalid")


def build_entry_execution_plan(
    inputs: EntryPlanningInputs,
) -> EntryExecutionPlan | ExecutionRejection:
    target = inputs.intent.target_execution_time_utc_ms
    if inputs.target_open is None:
        if inputs.watermark.event_watermark_time_utc_ms < target:
            raise ValueError("target event has not reached the planning watermark")
        return _reject(inputs, ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE)
    if inputs.account is None:
        return _reject(inputs, ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE)
    if inputs.account_evidence_bundle is None or inputs.account_evidence_records is None:
        return _reject(inputs, ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE)
    try:
        replayed_account = make_account_planning_snapshot(
            inputs.account_evidence_bundle,
            inputs.account_evidence_records,
            eligible_time_utc_ms=target,
        )
    except RequiredAccountEvidenceUnavailableError:
        return _reject(inputs, ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE)
    except ValueError:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if replayed_account != inputs.account:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if isinstance(inputs.contract, UnavailableContractRuleCoverage):
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE)
    if inputs.cost is None:
        return _reject(inputs, ExecutionRejectionReason.COST_MODEL_UNAVAILABLE)
    try:
        ensure_contract_usable(inputs.contract, inputs.stage)
    except ContractRuleUnavailableError:
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE)
    except ContractRuleExpiredError:
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_EXPIRED)
    except ValueError:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if not isinstance(inputs.funding_risk, CoveredFundingRiskConfigSnapshot):
        return _reject(inputs, ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE)
    try:
        _validate_chain(inputs)
    except ValueError:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if inputs.account.experiment_state is ExperimentState.HALTED:
        return _reject(inputs, ExecutionRejectionReason.EXPERIMENT_HALTED)
    if inputs.intent.symbol in inputs.account.existing_position_symbols:
        return _reject(inputs, ExecutionRejectionReason.EXISTING_POSITION)
    maximum_exit = target + 172_800_000
    try:
        funding_count = count_funding_events(target, maximum_exit, inputs.funding_schedule)
    except FundingScheduleUnverifiedError:
        return _reject(inputs, ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED)
    rate_cap = effective_adverse_rate_cap(inputs.funding_risk)
    if (
        funding_count != inputs.sizing.funding_event_upper_bound
        or rate_cap != inputs.sizing.effective_adverse_rate_cap
    ):
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    quantity = inputs.accepted_item.final_quantity
    notional = quantity * inputs.sizing.expected_entry_fill_price
    planned_risk = quantity * inputs.sizing.unit_risk
    entry_fee_value = entry_fee(quantity, inputs.sizing.expected_entry_fill_price, inputs.cost)
    exit_fee_value = exit_fee_reserve(
        quantity, inputs.sizing.planned_exit_notional_price_basis, inputs.cost
    )
    funding_reserve_value = funding_reserve(
        quantity,
        inputs.sizing.funding_notional_price_basis,
        rate_cap,
        funding_count,
    )
    required_cash = notional + entry_fee_value + exit_fee_value + funding_reserve_value
    if (
        inputs.accepted_item.final_notional != notional
        or inputs.accepted_item.final_planned_risk != planned_risk
        or inputs.accepted_item.final_required_cash != required_cash
    ):
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    accepted_risk = sum(
        item.final_planned_risk
        for item in inputs.scaling.item_results
        if isinstance(item, AcceptedScalingItem)
    )
    total_risk = (
        inputs.account.existing_open_risk + inputs.account.pending_plan_risk + accepted_risk
    )
    if total_risk > inputs.account.current_equity * Decimal("0.01"):
        return _reject(inputs, ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT)
    approximation_watermark = (
        inputs.contract.approximation_watermark
        if isinstance(inputs.contract, ApproximatedContractRuleCoverage)
        else "VERIFIED"
    )
    payload = {
        "schema_version": ENTRY_EXECUTION_PLAN_SCHEMA_VERSION,
        "intent_id": inputs.intent.intent_id,
        "candidate_id": inputs.intent.candidate_id,
        "computational_experiment_id": inputs.intent.computational_experiment_id,
        "portfolio_planning_batch_id": inputs.batch.batch_id,
        "portfolio_planning_batch_content_hash": inputs.batch.batch_content_hash,
        "portfolio_scaling_result_id": inputs.scaling.result_id,
        "portfolio_scaling_result_content_hash": inputs.scaling.result_content_hash,
        "accepted_scaling_item_id": inputs.accepted_item.item_id,
        "accepted_scaling_item_content_hash": inputs.accepted_item.item_content_hash,
        "symbol": inputs.intent.symbol,
        "side": inputs.intent.side,
        "decision_time_utc_ms": inputs.intent.candidate_decision_time_utc_ms,
        "target_execution_time_utc_ms": target,
        "plan_created_time_utc_ms": target,
        "maximum_exit_time_utc_ms": maximum_exit,
        "order_type": OrderType.MARKET_AT_1M_OPEN,
        "trigger_basis": TriggerBasis.TRADE_1M_OPEN,
        "target_open_snapshot_id": inputs.target_open.snapshot_id,
        "reference_price": inputs.target_open.open_price,
        "expected_entry_fill_price": inputs.sizing.expected_entry_fill_price,
        "stop_trigger_price": inputs.sizing.stop_trigger_price,
        "take_profit_trigger_price": inputs.sizing.take_profit_trigger_price,
        "expected_stop_fill_price": inputs.sizing.expected_stop_fill_price,
        "expected_take_profit_fill_price": inputs.sizing.expected_take_profit_fill_price,
        "planned_exit_notional_price_basis": (inputs.sizing.planned_exit_notional_price_basis),
        "funding_notional_price_basis": inputs.sizing.funding_notional_price_basis,
        "quantity": quantity,
        "notional": notional,
        "unit_risk": inputs.sizing.unit_risk,
        "single_risk_budget": inputs.sizing.single_risk_budget,
        "planned_risk": planned_risk,
        "existing_open_risk": inputs.account.existing_open_risk,
        "pending_plan_risk": inputs.account.pending_plan_risk,
        "total_risk_after_plan": total_risk,
        "initial_margin": notional,
        "entry_fee": entry_fee_value,
        "exit_fee_reserve": exit_fee_value,
        "funding_event_upper_bound": funding_count,
        "effective_adverse_rate_cap": rate_cap,
        "funding_reserve": funding_reserve_value,
        "required_cash": required_cash,
        "leverage": 1,
        "margin_mode": MarginMode.ISOLATED,
        "position_mode": PositionMode.ONE_WAY,
        "execution_delay_minutes": inputs.intent.execution_delay_minutes,
        "execution_time_config_version": inputs.intent.execution_time_config_version,
        "contract_rule_mode": ContractRuleMode(inputs.contract.mode),
        "contract_rule_coverage_id": inputs.contract.coverage_id,
        "contract_rule_coverage_content_hash": inputs.contract.coverage_content_hash,
        "contract_rule_version": inputs.contract.rule_version,
        "cost_model_snapshot_id": inputs.cost.snapshot_id,
        "cost_model_snapshot_content_hash": inputs.cost.snapshot_content_hash,
        "funding_schedule_version": inputs.funding_schedule.schedule_version,
        "funding_schedule_content_hash": inputs.funding_schedule.schedule_content_hash,
        "funding_risk_config_id": inputs.funding_risk.config_id,
        "funding_risk_config_content_hash": inputs.funding_risk.content_hash,
        "funding_risk_config_version": inputs.funding_risk.version,
        "account_snapshot_id": inputs.account.snapshot_id,
        "account_snapshot_hash": inputs.account.snapshot_hash,
        "position_sizing_result_id": inputs.sizing.result_id,
        "target_minute_input_hash": inputs.target_open.snapshot_content_hash,
        "decision_visible_input_hash": inputs.intent.decision_visible_input_hash,
        "plan_config_hash": plan_config_hash(ENTRY_EXECUTION_PLAN_SCHEMA_VERSION),
        "code_commit": inputs.code_commit,
        "dependency_lock_hash": inputs.dependency_lock_hash,
        "approximation_watermark": approximation_watermark,
    }
    return entry_execution_plan(payload)


def validate_entry_evidence_chain(plan: EntryExecutionPlan, inputs: EntryPlanningInputs) -> None:
    rebuilt = build_entry_execution_plan(inputs)
    if not isinstance(rebuilt, EntryExecutionPlan) or rebuilt != plan:
        raise ValueError("EntryExecutionPlan does not match its evidence chain")
