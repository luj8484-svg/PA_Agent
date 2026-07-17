from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import (
    ContractRuleMode,
    MarginMode,
    OrderType,
    PositionMode,
    ScheduledExitReason,
    Side,
    TriggerBasis,
)
from pa_agent.research_backtest.versions import (
    ACCOUNT_EQUITY_MODEL_VERSION,
    ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    CANONICAL_2B_VERSION,
    CONTRACT_MINIMUM_VERSION,
    ENTRY_EXECUTION_PLAN_SCHEMA_VERSION,
    EXECUTION_TIME_CONFIG_VERSION,
    EXIT_EXECUTION_PLAN_SCHEMA_VERSION,
    FEE_MODEL_VERSION,
    FUNDING_RISK_CONFIG_VERSION,
    FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_VERSION,
    GAP_POLICY_VERSION,
    LEVERAGE_POLICY_VERSION,
    PLANNING_PHASE_VERSION,
    PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION,
    PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION,
    PORTFOLIO_SCALING_MODEL_VERSION,
    POSITION_SIZING_MODEL_VERSION,
    PRICE_GEOMETRY_VERSION,
    REJECTION_PRIORITY_VERSION,
    SLIPPAGE_MODEL_VERSION,
    VALUATION_BASIS_VERSION,
)


def _decimal(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{name} has an invalid sign")


def plan_config_hash(plan_schema_version: str) -> str:
    return canonical_sha256(
        {
            "execution_time_version": EXECUTION_TIME_CONFIG_VERSION,
            "gap_version": GAP_POLICY_VERSION,
            "price_geometry_version": PRICE_GEOMETRY_VERSION,
            "fee_model_version": FEE_MODEL_VERSION,
            "slippage_model_version": SLIPPAGE_MODEL_VERSION,
            "funding_schedule_version": FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_VERSION,
            "funding_risk_version": FUNDING_RISK_CONFIG_VERSION,
            "sizing_version": POSITION_SIZING_MODEL_VERSION,
            "scaling_version": PORTFOLIO_SCALING_MODEL_VERSION,
            "batch_completeness_schema_version": (
                PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_VERSION
            ),
            "batch_completeness_policy_version": (PORTFOLIO_BATCH_COMPLETENESS_POLICY_VERSION),
            "account_evidence_bundle_schema_version": (
                ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION
            ),
            "equity_model_version": ACCOUNT_EQUITY_MODEL_VERSION,
            "valuation_basis_version": VALUATION_BASIS_VERSION,
            "contract_minimum_version": CONTRACT_MINIMUM_VERSION,
            "leverage_policy_version": LEVERAGE_POLICY_VERSION,
            "rejection_priority_version": REJECTION_PRIORITY_VERSION,
            "canonical_version": CANONICAL_2B_VERSION,
            "entry_or_exit_plan_schema_version": plan_schema_version,
            "planning_phase_version": PLANNING_PHASE_VERSION,
        }
    )


@dataclass(frozen=True, slots=True)
class EntryExecutionPlan:
    schema_version: str
    plan_id: str
    plan_content_hash: str
    intent_id: str
    candidate_id: str
    computational_experiment_id: str
    portfolio_planning_batch_id: str
    portfolio_planning_batch_content_hash: str
    portfolio_scaling_result_id: str
    portfolio_scaling_result_content_hash: str
    accepted_scaling_item_id: str
    accepted_scaling_item_content_hash: str
    symbol: str
    side: Side
    decision_time_utc_ms: int
    target_execution_time_utc_ms: int
    plan_created_time_utc_ms: int
    maximum_exit_time_utc_ms: int
    order_type: OrderType
    trigger_basis: TriggerBasis
    target_open_snapshot_id: str
    reference_price: Decimal
    expected_entry_fill_price: Decimal
    stop_trigger_price: Decimal
    take_profit_trigger_price: Decimal
    expected_stop_fill_price: Decimal
    expected_take_profit_fill_price: Decimal
    planned_exit_notional_price_basis: Decimal
    funding_notional_price_basis: Decimal
    quantity: Decimal
    notional: Decimal
    unit_risk: Decimal
    single_risk_budget: Decimal
    planned_risk: Decimal
    existing_open_risk: Decimal
    pending_plan_risk: Decimal
    total_risk_after_plan: Decimal
    initial_margin: Decimal
    entry_fee: Decimal
    exit_fee_reserve: Decimal
    funding_event_upper_bound: int
    effective_adverse_rate_cap: Decimal
    funding_reserve: Decimal
    required_cash: Decimal
    leverage: int
    margin_mode: MarginMode
    position_mode: PositionMode
    execution_delay_minutes: int
    execution_time_config_version: str
    contract_rule_mode: ContractRuleMode
    contract_rule_coverage_id: str
    contract_rule_coverage_content_hash: str
    contract_rule_version: str
    cost_model_snapshot_id: str
    cost_model_snapshot_content_hash: str
    funding_schedule_version: str
    funding_schedule_content_hash: str
    funding_risk_config_id: str
    funding_risk_config_content_hash: str
    funding_risk_config_version: str
    account_snapshot_id: str
    account_snapshot_hash: str
    position_sizing_result_id: str
    target_minute_input_hash: str
    decision_visible_input_hash: str
    plan_config_hash: str
    code_commit: str
    dependency_lock_hash: str
    approximation_watermark: str

    def __post_init__(self) -> None:
        if self.schema_version != ENTRY_EXECUTION_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported EntryExecutionPlan schema")
        if type(self.leverage) is not int or self.leverage != 1:
            raise ValueError("entry plan leverage must be the exact integer 1")
        if type(self.execution_delay_minutes) is not int:
            raise ValueError("entry execution delay must be an exact integer")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.side, Side):
            raise ValueError("invalid entry plan market identity")
        for name in (
            "decision_time_utc_ms",
            "target_execution_time_utc_ms",
            "plan_created_time_utc_ms",
            "maximum_exit_time_utc_ms",
        ):
            require_utc_ms(getattr(self, name), name)
        if self.plan_created_time_utc_ms != self.target_execution_time_utc_ms:
            raise ValueError("plan creation time must equal target market event time")
        if self.maximum_exit_time_utc_ms != self.target_execution_time_utc_ms + 172_800_000:
            raise ValueError("maximum exit time must be exactly 48 hours after target")
        if self.order_type is not OrderType.MARKET_AT_1M_OPEN:
            raise ValueError("unsupported entry order type")
        if self.trigger_basis is not TriggerBasis.TRADE_1M_OPEN:
            raise ValueError("unsupported entry trigger basis")
        for name in (
            "reference_price",
            "expected_entry_fill_price",
            "stop_trigger_price",
            "take_profit_trigger_price",
            "expected_stop_fill_price",
            "expected_take_profit_fill_price",
            "planned_exit_notional_price_basis",
            "funding_notional_price_basis",
            "quantity",
            "notional",
            "unit_risk",
            "single_risk_budget",
            "planned_risk",
            "initial_margin",
            "required_cash",
        ):
            _decimal(getattr(self, name), name, positive=True)
        for name in (
            "existing_open_risk",
            "pending_plan_risk",
            "total_risk_after_plan",
            "entry_fee",
            "exit_fee_reserve",
            "effective_adverse_rate_cap",
            "funding_reserve",
        ):
            _decimal(getattr(self, name), name)
        if self.funding_notional_price_basis != self.planned_exit_notional_price_basis:
            raise ValueError("funding price basis must equal the exit envelope")
        if self.notional != self.quantity * self.expected_entry_fill_price:
            raise ValueError("entry notional contradicts quantity and fill price")
        if self.planned_risk != self.quantity * self.unit_risk:
            raise ValueError("planned risk contradicts quantity and unit risk")
        if self.planned_risk > self.single_risk_budget:
            raise ValueError("planned risk exceeds the single-trade budget")
        if self.initial_margin != self.notional:
            raise ValueError("fixed 1x initial margin must equal notional")
        if self.required_cash != (
            self.initial_margin + self.entry_fee + self.exit_fee_reserve + self.funding_reserve
        ):
            raise ValueError("required cash contradicts the four frozen components")
        if type(self.funding_event_upper_bound) is not int or self.funding_event_upper_bound < 0:
            raise ValueError("funding event upper bound must be nonnegative integer")
        if self.leverage != 1 or self.margin_mode is not MarginMode.ISOLATED:
            raise ValueError("entry plan must use isolated fixed 1x leverage")
        if self.position_mode is not PositionMode.ONE_WAY:
            raise ValueError("entry plan must use one-way position mode")
        if self.execution_delay_minutes not in {0, 1, 2}:
            raise ValueError("unsupported execution delay")
        if self.execution_time_config_version != EXECUTION_TIME_CONFIG_VERSION:
            raise ValueError("unsupported execution-time version")
        if self.contract_rule_mode is ContractRuleMode.UNAVAILABLE:
            raise ValueError("unavailable contract cannot enter a plan")
        expected_watermark = (
            "VERIFIED"
            if self.contract_rule_mode is ContractRuleMode.VERIFIED
            else "APPROXIMATED_NOT_LIVE_ELIGIBLE"
        )
        if self.approximation_watermark != expected_watermark:
            raise ValueError("plan approximation watermark contradicts contract mode")
        for name in (
            "intent_id",
            "candidate_id",
            "portfolio_planning_batch_id",
            "portfolio_scaling_result_id",
            "accepted_scaling_item_id",
            "target_open_snapshot_id",
            "contract_rule_coverage_id",
            "contract_rule_version",
            "cost_model_snapshot_id",
            "funding_schedule_version",
            "funding_risk_config_id",
            "funding_risk_config_version",
            "account_snapshot_id",
            "position_sizing_result_id",
        ):
            require_nonempty_string(getattr(self, name), name)
        for name in (
            "computational_experiment_id",
            "portfolio_planning_batch_content_hash",
            "portfolio_scaling_result_content_hash",
            "accepted_scaling_item_content_hash",
            "contract_rule_coverage_content_hash",
            "cost_model_snapshot_content_hash",
            "funding_schedule_content_hash",
            "funding_risk_config_content_hash",
            "account_snapshot_hash",
            "target_minute_input_hash",
            "decision_visible_input_hash",
            "plan_config_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        if self.plan_config_hash != plan_config_hash(ENTRY_EXECUTION_PLAN_SCHEMA_VERSION):
            raise ValueError("plan config hash does not match frozen versions")
        require_commit(self.code_commit)
        verify_formal_identity(
            self, id_field="plan_id", hash_field="plan_content_hash", prefix="eplan_"
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def entry_execution_plan(payload: dict[str, object]) -> EntryExecutionPlan:
    plan_id, digest = formal_identity("eplan_", payload)
    return EntryExecutionPlan(plan_id=plan_id, plan_content_hash=digest, **payload)


@dataclass(frozen=True, slots=True)
class ExitExecutionPlan:
    schema_version: str
    plan_id: str
    plan_content_hash: str
    intent_id: str
    condition_event_id: str
    origin_candidate_id: str
    position_id: str
    computational_experiment_id: str
    symbol: str
    position_side: Side
    scheduled_exit_reason: ScheduledExitReason
    quantity: Decimal
    condition_time_utc_ms: int
    target_execution_time_utc_ms: int
    plan_created_time_utc_ms: int
    order_type: OrderType
    trigger_basis: TriggerBasis
    target_open_snapshot_id: str
    reference_price: Decimal
    expected_exit_fill_price: Decimal
    expected_exit_fee: Decimal
    contract_rule_mode: ContractRuleMode
    contract_rule_coverage_id: str
    contract_rule_coverage_content_hash: str
    cost_model_snapshot_id: str
    cost_model_snapshot_content_hash: str
    target_minute_input_hash: str
    position_snapshot_hash: str
    plan_config_hash: str
    code_commit: str
    dependency_lock_hash: str
    approximation_watermark: str

    def __post_init__(self) -> None:
        if self.schema_version != EXIT_EXECUTION_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported ExitExecutionPlan schema")
        for name in (
            "intent_id",
            "condition_event_id",
            "origin_candidate_id",
            "position_id",
            "target_open_snapshot_id",
            "contract_rule_coverage_id",
            "cost_model_snapshot_id",
        ):
            require_nonempty_string(getattr(self, name), name)
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.position_side, Side):
            raise ValueError("invalid exit plan market identity")
        if not isinstance(self.scheduled_exit_reason, ScheduledExitReason):
            raise ValueError("ExitExecutionPlan only accepts scheduled reasons")
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.reference_price, "reference_price", positive=True)
        _decimal(self.expected_exit_fill_price, "expected_exit_fill_price", positive=True)
        _decimal(self.expected_exit_fee, "expected_exit_fee")
        for name in (
            "condition_time_utc_ms",
            "target_execution_time_utc_ms",
            "plan_created_time_utc_ms",
        ):
            require_utc_ms(getattr(self, name), name)
        if self.target_execution_time_utc_ms <= self.condition_time_utc_ms:
            raise ValueError("exit target must be strictly after condition")
        if self.plan_created_time_utc_ms != self.target_execution_time_utc_ms:
            raise ValueError("exit plan creation time must equal target event time")
        if self.order_type is not OrderType.MARKET_AT_1M_OPEN:
            raise ValueError("unsupported exit order type")
        if self.trigger_basis is not TriggerBasis.TRADE_1M_OPEN:
            raise ValueError("unsupported exit trigger basis")
        if self.contract_rule_mode is ContractRuleMode.UNAVAILABLE:
            raise ValueError("unavailable contract cannot enter an exit plan")
        expected_watermark = (
            "VERIFIED"
            if self.contract_rule_mode is ContractRuleMode.VERIFIED
            else "APPROXIMATED_NOT_LIVE_ELIGIBLE"
        )
        if self.approximation_watermark != expected_watermark:
            raise ValueError("exit plan approximation watermark contradicts contract mode")
        for name in (
            "computational_experiment_id",
            "contract_rule_coverage_content_hash",
            "cost_model_snapshot_content_hash",
            "target_minute_input_hash",
            "position_snapshot_hash",
            "plan_config_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        if self.plan_config_hash != plan_config_hash(EXIT_EXECUTION_PLAN_SCHEMA_VERSION):
            raise ValueError("exit plan config hash does not match frozen versions")
        require_commit(self.code_commit)
        verify_formal_identity(
            self, id_field="plan_id", hash_field="plan_content_hash", prefix="xplan_"
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def exit_execution_plan(payload: dict[str, object]) -> ExitExecutionPlan:
    plan_id, digest = formal_identity("xplan_", payload)
    return ExitExecutionPlan(plan_id=plan_id, plan_content_hash=digest, **payload)
