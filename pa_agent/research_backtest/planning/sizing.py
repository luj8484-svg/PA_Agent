from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import AccountPlanningSnapshot
from pa_agent.research_backtest.domain.contracts import (
    ContractRuleCoverage,
    UnavailableContractRuleCoverage,
)
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.domain.funding import FundingRiskConfigSnapshot
from pa_agent.research_backtest.domain.sizing import (
    PositionSizingResult,
    SizingRejected,
    position_sizing_result,
)
from pa_agent.research_backtest.planning.funding import effective_adverse_rate_cap
from pa_agent.research_backtest.planning.prices import floor_to_step, price_geometry
from pa_agent.research_backtest.versions import (
    POSITION_SIZING_MODEL_VERSION,
    POSITION_SIZING_RESULT_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class SizingInputs:
    intent_id: str
    symbol: str
    side: Side
    reference_price: Decimal
    atr: Decimal
    contract: ContractRuleCoverage
    cost: CostModelSnapshot
    funding_risk: FundingRiskConfigSnapshot
    funding_event_upper_bound: int
    account: AccountPlanningSnapshot


def position_sizing(inputs: SizingInputs) -> PositionSizingResult:
    if isinstance(inputs.contract, UnavailableContractRuleCoverage):
        raise SizingRejected("CONTRACT_RULE_UNAVAILABLE")
    if inputs.symbol != inputs.contract.symbol or inputs.symbol != inputs.cost.symbol:
        raise ValueError("sizing symbol does not match contract/cost evidence")
    if inputs.symbol != inputs.funding_risk.symbol:
        raise ValueError("sizing symbol does not match funding-risk evidence")
    if type(inputs.funding_event_upper_bound) is not int or inputs.funding_event_upper_bound < 0:
        raise ValueError("funding event upper bound must be nonnegative integer")
    geometry = price_geometry(
        inputs.side,
        inputs.reference_price,
        inputs.atr,
        inputs.cost,
        inputs.contract,
    )
    funding_rate = effective_adverse_rate_cap(inputs.funding_risk)
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
        raise SizingRejected("QUANTITY_ROUNDED_TO_ZERO")
    if step_quantity < inputs.contract.min_qty:
        raise SizingRejected("BELOW_MIN_QTY")
    if step_quantity * entry < inputs.contract.min_notional:
        raise SizingRejected("BELOW_MIN_NOTIONAL")
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
        "reference_price": inputs.reference_price,
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
