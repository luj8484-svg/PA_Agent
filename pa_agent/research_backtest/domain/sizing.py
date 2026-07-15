from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_nonempty_string,
    require_sha256,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.versions import (
    POSITION_SIZING_MODEL_VERSION,
    POSITION_SIZING_RESULT_SCHEMA_VERSION,
)


class SizingRejected(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _decimal(value: Decimal, name: str, *, positive: bool = True) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{name} has an invalid sign")


@dataclass(frozen=True, slots=True)
class PositionSizingResult:
    schema_version: str
    result_id: str
    result_content_hash: str
    intent_id: str
    symbol: str
    side: Side
    reference_price: Decimal
    expected_entry_fill_price: Decimal
    stop_trigger_price: Decimal
    take_profit_trigger_price: Decimal
    expected_stop_fill_price: Decimal
    expected_take_profit_fill_price: Decimal
    planned_exit_notional_price_basis: Decimal
    funding_notional_price_basis: Decimal
    unit_risk: Decimal
    single_risk_budget: Decimal
    raw_quantity: Decimal
    step_quantized_quantity: Decimal
    unscaled_planned_risk: Decimal
    unscaled_required_cash: Decimal
    contract_rule_coverage_id: str
    cost_model_snapshot_id: str
    funding_risk_config_id: str
    funding_event_upper_bound: int
    effective_adverse_rate_cap: Decimal
    account_snapshot_id: str
    account_snapshot_hash: str
    sizing_model_version: str

    def __post_init__(self) -> None:
        if self.schema_version != POSITION_SIZING_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported position sizing result schema")
        require_nonempty_string(self.intent_id, "intent_id")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.side, Side):
            raise ValueError("invalid sizing market identity")
        for name in (
            "reference_price",
            "expected_entry_fill_price",
            "stop_trigger_price",
            "take_profit_trigger_price",
            "expected_stop_fill_price",
            "expected_take_profit_fill_price",
            "planned_exit_notional_price_basis",
            "funding_notional_price_basis",
            "unit_risk",
            "single_risk_budget",
            "raw_quantity",
            "unscaled_planned_risk",
            "unscaled_required_cash",
        ):
            _decimal(getattr(self, name), name)
        _decimal(self.step_quantized_quantity, "step_quantized_quantity")
        _decimal(self.effective_adverse_rate_cap, "effective_adverse_rate_cap", positive=False)
        if self.funding_notional_price_basis != self.planned_exit_notional_price_basis:
            raise ValueError("funding basis must equal the frozen exit envelope")
        if self.planned_exit_notional_price_basis != max(
            self.expected_entry_fill_price,
            self.expected_stop_fill_price,
            self.expected_take_profit_fill_price,
        ):
            raise ValueError("planned exit basis must equal the frozen price envelope")
        if self.side is Side.LONG:
            geometry_valid = (
                self.expected_stop_fill_price
                <= self.stop_trigger_price
                < self.expected_entry_fill_price
                < self.take_profit_trigger_price
                and self.expected_take_profit_fill_price > self.expected_entry_fill_price
            )
        else:
            geometry_valid = (
                self.expected_take_profit_fill_price
                < self.expected_entry_fill_price
                < self.stop_trigger_price
                <= self.expected_stop_fill_price
            )
        if not geometry_valid:
            raise ValueError("sizing result contains invalid price geometry")
        if self.unscaled_planned_risk != self.raw_quantity * self.unit_risk:
            raise ValueError("unscaled planned risk contradicts raw quantity")
        if self.step_quantized_quantity * self.unit_risk > self.single_risk_budget:
            raise ValueError("step quantity exceeds the single-trade risk budget")
        for name in (
            "contract_rule_coverage_id",
            "cost_model_snapshot_id",
            "funding_risk_config_id",
            "account_snapshot_id",
        ):
            require_nonempty_string(getattr(self, name), name)
        if type(self.funding_event_upper_bound) is not int or self.funding_event_upper_bound < 0:
            raise ValueError("funding event upper bound must be nonnegative integer")
        require_sha256(self.account_snapshot_hash, "account_snapshot_hash")
        if self.sizing_model_version != POSITION_SIZING_MODEL_VERSION:
            raise ValueError("unsupported sizing model")
        verify_formal_identity(
            self,
            id_field="result_id",
            hash_field="result_content_hash",
            prefix="size_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def position_sizing_result(payload: dict[str, object]) -> PositionSizingResult:
    result_id, digest = formal_identity("size_", payload)
    return PositionSizingResult(result_id=result_id, result_content_hash=digest, **payload)
