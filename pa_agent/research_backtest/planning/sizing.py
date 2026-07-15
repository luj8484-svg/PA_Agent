from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import (
    AccountEvidenceRecords,
    AccountPlanningEvidenceBundle,
    AccountPlanningSnapshot,
    OpenRiskEvidence,
    RequiredAccountEvidenceUnavailableError,
    make_account_planning_snapshot,
)
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.contracts import (
    ContractRuleCoverage,
    ContractRuleExpiredError,
    ContractRuleUnavailableError,
    UnavailableContractRuleCoverage,
    ensure_contract_usable,
)
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ResearchStage,
    Side,
)
from pa_agent.research_backtest.domain.funding import (
    FundingRiskConfigSnapshot,
    FundingRiskConfigUnavailableError,
)
from pa_agent.research_backtest.domain.market_inputs import TargetMinuteOpenSnapshot
from pa_agent.research_backtest.domain.rejections import (
    EntryIntentSubjectRef,
    ExecutionRejection,
    rejection_fact,
)
from pa_agent.research_backtest.domain.sizing import (
    PositionSizingResult,
    SizingRejected,
    position_sizing_result,
)
from pa_agent.research_backtest.planning.funding import effective_adverse_rate_cap
from pa_agent.research_backtest.planning.prices import adverse_gap, floor_to_step, price_geometry
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.versions import (
    POSITION_SIZING_MODEL_VERSION,
    POSITION_SIZING_RESULT_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class SizingInputs:
    intent_id: str
    symbol: str
    side: Side
    candidate: StrategyCandidate
    target_open: TargetMinuteOpenSnapshot
    contract: ContractRuleCoverage
    cost: CostModelSnapshot | None
    funding_risk: FundingRiskConfigSnapshot
    funding_event_upper_bound: int
    account: AccountPlanningSnapshot
    account_evidence_bundle: AccountPlanningEvidenceBundle | None
    account_evidence_records: AccountEvidenceRecords | None
    open_risk_evidence_records: tuple[OpenRiskEvidence, ...] | None
    subject: EntryIntentSubjectRef
    stage: ResearchStage
    code_commit: str
    dependency_lock_hash: str


def _reject(inputs: SizingInputs, reason: str | ExecutionRejectionReason) -> ExecutionRejection:
    version_hashes = [
        ("account", inputs.account.snapshot_hash),
        ("contract", inputs.contract.coverage_content_hash),
    ]
    if inputs.cost is not None:
        version_hashes.append(("cost", inputs.cost.snapshot_content_hash))
    return choose_rejection(
        subject=inputs.subject,
        event_time_utc_ms=inputs.account.event_time_utc_ms,
        facts=(rejection_fact(reason),),
        stage=inputs.stage,
        relevant_version_hashes=tuple(sorted(version_hashes)),
        code_commit=inputs.code_commit,
        dependency_lock_hash=inputs.dependency_lock_hash,
    )


def position_sizing(inputs: SizingInputs) -> PositionSizingResult | ExecutionRejection:
    if inputs.subject.entry_intent_id != inputs.intent_id:
        raise ValueError("sizing subject does not match entry Intent")
    if not isinstance(inputs.stage, ResearchStage):
        raise ValueError("invalid sizing research stage")
    if isinstance(inputs.contract, UnavailableContractRuleCoverage):
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE)
    try:
        ensure_contract_usable(inputs.contract, inputs.stage)
    except ContractRuleUnavailableError:
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE)
    except ContractRuleExpiredError:
        return _reject(inputs, ExecutionRejectionReason.CONTRACT_RULE_EXPIRED)
    except ValueError:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if inputs.cost is None:
        return _reject(inputs, ExecutionRejectionReason.COST_MODEL_UNAVAILABLE)
    if inputs.account_evidence_bundle is None or inputs.account_evidence_records is None:
        return _reject(inputs, ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE)
    if inputs.open_risk_evidence_records is None:
        return _reject(inputs, ExecutionRejectionReason.OPEN_RISK_MODEL_UNAVAILABLE)
    if inputs.open_risk_evidence_records != inputs.account_evidence_records.open_risks:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    try:
        replayed = make_account_planning_snapshot(
            inputs.account_evidence_bundle,
            inputs.account_evidence_records,
            eligible_time_utc_ms=inputs.account.event_time_utc_ms,
        )
    except RequiredAccountEvidenceUnavailableError:
        return _reject(inputs, ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE)
    except ValueError:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if replayed != inputs.account:
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if (
        inputs.candidate.candidate_id != inputs.subject.candidate_id
        or inputs.candidate.symbol != inputs.symbol
        or inputs.candidate.market_view.value != inputs.side.value
        or inputs.target_open.symbol != inputs.symbol
    ):
        return _reject(inputs, ExecutionRejectionReason.DATA_INVALID)
    if inputs.symbol != inputs.contract.symbol or inputs.symbol != inputs.cost.symbol:
        raise ValueError("sizing symbol does not match contract/cost evidence")
    if inputs.symbol != inputs.funding_risk.symbol:
        raise ValueError("sizing symbol does not match funding-risk evidence")
    if type(inputs.funding_event_upper_bound) is not int or inputs.funding_event_upper_bound < 0:
        raise ValueError("funding event upper bound must be nonnegative integer")
    try:
        adverse_gap(
            inputs.side,
            inputs.candidate.decision_close,
            inputs.target_open.open_price,
            inputs.candidate.atr14_4h,
        )
        geometry = price_geometry(
            inputs.side,
            inputs.target_open.open_price,
            inputs.candidate.atr14_4h,
            inputs.cost,
            inputs.contract,
        )
    except SizingRejected as error:
        return _reject(inputs, error.reason)
    try:
        funding_rate = effective_adverse_rate_cap(inputs.funding_risk)
    except FundingRiskConfigUnavailableError:
        return _reject(inputs, ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE)
    entry = geometry.expected_entry_fill_price
    stop_fill = geometry.expected_stop_fill_price
    exit_basis = geometry.planned_exit_notional_price_basis
    fee_rate = inputs.cost.effective_fee_rate
    unit_risk = (
        abs(entry - stop_fill)
        + entry * fee_rate
        + stop_fill * fee_rate
        + exit_basis * funding_rate * inputs.funding_event_upper_bound
    )
    if unit_risk <= 0:
        raise ValueError("unit risk must be positive")
    budget = inputs.account.current_equity * Decimal("0.005")
    if budget <= 0:
        raise ValueError("single risk budget must be positive")
    raw_quantity = budget / unit_risk
    step_quantity = floor_to_step(raw_quantity, inputs.contract.step_size)
    if step_quantity == 0:
        return _reject(inputs, ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO)
    if step_quantity < inputs.contract.min_qty:
        return _reject(inputs, ExecutionRejectionReason.BELOW_MIN_QTY)
    if step_quantity * entry < inputs.contract.min_notional:
        return _reject(inputs, ExecutionRejectionReason.BELOW_MIN_NOTIONAL)
    planned_risk = step_quantity * unit_risk
    if planned_risk > budget:
        raise ValueError("floor-quantized quantity exceeded risk budget")
    unscaled_planned_risk = raw_quantity * unit_risk
    raw_notional = raw_quantity * entry
    raw_entry_fee = raw_quantity * entry * fee_rate
    raw_exit_fee = raw_quantity * exit_basis * fee_rate
    raw_funding = raw_quantity * exit_basis * funding_rate * inputs.funding_event_upper_bound
    unscaled_required_cash = raw_notional + raw_entry_fee + raw_exit_fee + raw_funding
    payload = {
        "schema_version": POSITION_SIZING_RESULT_SCHEMA_VERSION,
        "intent_id": inputs.intent_id,
        "symbol": inputs.symbol,
        "side": inputs.side,
        "reference_price": inputs.target_open.open_price,
        "expected_entry_fill_price": entry,
        "stop_trigger_price": geometry.stop_trigger_price,
        "take_profit_trigger_price": geometry.take_profit_trigger_price,
        "expected_stop_fill_price": stop_fill,
        "expected_take_profit_fill_price": geometry.expected_take_profit_fill_price,
        "planned_exit_notional_price_basis": exit_basis,
        "funding_notional_price_basis": exit_basis,
        "unit_risk": unit_risk,
        "single_risk_budget": budget,
        "raw_quantity": raw_quantity,
        "step_quantized_quantity": step_quantity,
        "unscaled_planned_risk": unscaled_planned_risk,
        "unscaled_required_cash": unscaled_required_cash,
        "contract_rule_coverage_id": inputs.contract.coverage_id,
        "cost_model_snapshot_id": inputs.cost.snapshot_id,
        "funding_risk_config_id": inputs.funding_risk.config_id,
        "funding_event_upper_bound": inputs.funding_event_upper_bound,
        "effective_adverse_rate_cap": funding_rate,
        "account_snapshot_id": inputs.account.snapshot_id,
        "account_snapshot_hash": inputs.account.snapshot_hash,
        "sizing_model_version": POSITION_SIZING_MODEL_VERSION,
    }
    return position_sizing_result(payload)
