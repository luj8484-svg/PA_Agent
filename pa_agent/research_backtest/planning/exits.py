from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.base import require_commit, require_sha256
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.contracts import (
    ApproximatedContractRuleCoverage,
    ContractRuleCoverage,
    UnavailableContractRuleCoverage,
    ensure_contract_usable,
)
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import (
    ContractRuleMode,
    ExecutionRejectionReason,
    OrderType,
    ResearchStage,
    TriggerBasis,
)
from pa_agent.research_backtest.domain.intents import (
    ExitConditionSnapshot,
    ExitIntent,
    exit_intent,
)
from pa_agent.research_backtest.domain.market_inputs import (
    TargetEventWatermark,
    TargetMinuteOpenSnapshot,
)
from pa_agent.research_backtest.domain.plans import (
    ExitExecutionPlan,
    exit_execution_plan,
    plan_config_hash,
)
from pa_agent.research_backtest.domain.rejections import (
    ExecutionRejection,
    exit_intent_subject_ref,
    rejection_fact,
)
from pa_agent.research_backtest.planning.prices import expected_exit_price
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    EXIT_EXECUTION_PLAN_SCHEMA_VERSION,
    EXIT_INTENT_SCHEMA_VERSION,
)


def make_exit_intent(
    condition: ExitConditionSnapshot,
    config: ExecutionTimeConfig,
    *,
    computational_experiment_id: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> ExitIntent:
    require_sha256(computational_experiment_id, "computational_experiment_id")
    require_sha256(dependency_lock_hash, "dependency_lock_hash")
    require_commit(code_commit)
    anchor = (condition.condition_time_utc_ms // 60_000) * 60_000 + 60_000
    target = anchor + config.exit_delay_minutes * 60_000
    intent_config_hash = canonical_sha256(
        {
            "execution_time_config_id": config.config_id,
            "execution_time_config_content_hash": config.config_content_hash,
            "exit_intent_schema_version": EXIT_INTENT_SCHEMA_VERSION,
            "canonical_version": CANONICAL_2B_VERSION,
        }
    )
    payload = {
        "schema_version": EXIT_INTENT_SCHEMA_VERSION,
        "condition_event_id": condition.condition_event_id,
        "origin_candidate_id": condition.origin_candidate_id,
        "position_id": condition.position_id,
        "position_snapshot_hash": condition.position_snapshot_hash,
        "symbol": condition.symbol,
        "position_side": condition.position_side,
        "full_exit_quantity": condition.exit_quantity,
        "scheduled_exit_reason": condition.scheduled_exit_reason,
        "condition_visible_input_hash": condition.condition_visible_input_hash,
        "computational_experiment_id": computational_experiment_id,
        "condition_time_utc_ms": condition.condition_time_utc_ms,
        "intent_created_time_utc_ms": condition.condition_time_utc_ms,
        "execution_anchor_utc_ms": anchor,
        "target_execution_time_utc_ms": target,
        "execution_delay_minutes": config.exit_delay_minutes,
        "execution_time_config_id": config.config_id,
        "execution_time_config_content_hash": config.config_content_hash,
        "execution_time_config_version": config.version,
        "intent_config_hash": intent_config_hash,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    return exit_intent(payload)


@dataclass(frozen=True, slots=True)
class ExitPlanningInputs:
    intent: ExitIntent
    target_open: TargetMinuteOpenSnapshot
    watermark: TargetEventWatermark
    contract: ContractRuleCoverage
    cost: CostModelSnapshot
    target_position_snapshot_hash: str
    code_commit: str
    dependency_lock_hash: str


def _reject(inputs: ExitPlanningInputs, reason: ExecutionRejectionReason) -> ExecutionRejection:
    return choose_rejection(
        subject=exit_intent_subject_ref(inputs.intent),
        event_time_utc_ms=inputs.intent.target_execution_time_utc_ms,
        facts=(rejection_fact(reason),),
        stage=ResearchStage.BACKTEST,
        relevant_version_hashes=(
            ("contract", inputs.contract.coverage_content_hash),
            ("position", inputs.intent.position_snapshot_hash),
        ),
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )


def build_exit_execution_plan(
    inputs: ExitPlanningInputs,
) -> ExitExecutionPlan | ExecutionRejection:
    intent = inputs.intent
    target = intent.target_execution_time_utc_ms
    if inputs.target_position_snapshot_hash != intent.position_snapshot_hash:
        return _reject(inputs, ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED)
    if isinstance(inputs.contract, UnavailableContractRuleCoverage):
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE)
    ensure_contract_usable(inputs.contract, ResearchStage.BACKTEST)
    if (
        inputs.target_open.symbol != intent.symbol
        or inputs.target_open.open_time_utc_ms != target
        or inputs.watermark.symbol != intent.symbol
        or inputs.watermark.target_open_time_utc_ms != target
        or inputs.watermark.event_watermark_time_utc_ms < target
        or inputs.contract.symbol != intent.symbol
        or inputs.contract.query_time_utc_ms != target
        or inputs.cost.symbol != intent.symbol
    ):
        raise ValueError("exit planning evidence does not match ExitIntent")
    if intent.full_exit_quantity % inputs.contract.step_size != 0:
        return _reject(inputs, ExecutionRejectionReason.POSITION_QUANTITY_RULE_MISMATCH)
    fill_price = expected_exit_price(
        intent.position_side, inputs.target_open.open_price, inputs.cost, inputs.contract
    )
    expected_fee = intent.full_exit_quantity * fill_price * inputs.cost.effective_fee_rate
    approximation_watermark = (
        inputs.contract.approximation_watermark
        if isinstance(inputs.contract, ApproximatedContractRuleCoverage)
        else "VERIFIED"
    )
    payload = {
        "schema_version": EXIT_EXECUTION_PLAN_SCHEMA_VERSION,
        "intent_id": intent.intent_id,
        "condition_event_id": intent.condition_event_id,
        "origin_candidate_id": intent.origin_candidate_id,
        "position_id": intent.position_id,
        "computational_experiment_id": intent.computational_experiment_id,
        "symbol": intent.symbol,
        "position_side": intent.position_side,
        "scheduled_exit_reason": intent.scheduled_exit_reason,
        "quantity": intent.full_exit_quantity,
        "condition_time_utc_ms": intent.condition_time_utc_ms,
        "target_execution_time_utc_ms": target,
        "plan_created_time_utc_ms": target,
        "order_type": OrderType.MARKET_AT_1M_OPEN,
        "trigger_basis": TriggerBasis.TRADE_1M_OPEN,
        "target_open_snapshot_id": inputs.target_open.snapshot_id,
        "reference_price": inputs.target_open.open_price,
        "expected_exit_fill_price": fill_price,
        "expected_exit_fee": expected_fee,
        "contract_rule_mode": ContractRuleMode(inputs.contract.mode),
        "contract_rule_coverage_id": inputs.contract.coverage_id,
        "contract_rule_coverage_content_hash": inputs.contract.coverage_content_hash,
        "cost_model_snapshot_id": inputs.cost.snapshot_id,
        "cost_model_snapshot_content_hash": inputs.cost.snapshot_content_hash,
        "target_minute_input_hash": inputs.target_open.snapshot_content_hash,
        "position_snapshot_hash": intent.position_snapshot_hash,
        "plan_config_hash": plan_config_hash(EXIT_EXECUTION_PLAN_SCHEMA_VERSION),
        "code_commit": inputs.code_commit,
        "dependency_lock_hash": inputs.dependency_lock_hash,
        "approximation_watermark": approximation_watermark,
    }
    return exit_execution_plan(payload)
