from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.versions import (
    ACCEPTED_SCALING_ITEM_SCHEMA_VERSION,
    PORTFOLIO_SCALING_MODEL_VERSION,
    PORTFOLIO_SCALING_RESULT_SCHEMA_VERSION,
    REJECTED_SCALING_ITEM_SCHEMA_VERSION,
)


def _decimal(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{name} has an invalid sign")


@dataclass(frozen=True, slots=True)
class AcceptedScalingItem:
    schema_version: str
    item_id: str
    item_content_hash: str
    symbol: str
    sizing_result_id: str
    final_quantity: Decimal
    final_notional: Decimal
    final_planned_risk: Decimal
    final_required_cash: Decimal
    step_size: Decimal
    minimum_status: str

    def __post_init__(self) -> None:
        if self.schema_version != ACCEPTED_SCALING_ITEM_SCHEMA_VERSION:
            raise ValueError("unsupported accepted scaling item schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported scaling symbol")
        require_nonempty_string(self.sizing_result_id, "sizing_result_id")
        for name in (
            "final_quantity",
            "final_notional",
            "final_planned_risk",
            "final_required_cash",
            "step_size",
        ):
            _decimal(getattr(self, name), name, positive=True)
        if self.final_quantity % self.step_size != 0:
            raise ValueError("accepted quantity is not step aligned")
        if self.minimum_status != "PASSED_MIN_QTY_AND_NOTIONAL":
            raise ValueError("accepted scaling item has wrong minimum status")
        verify_formal_identity(
            self,
            id_field="item_id",
            hash_field="item_content_hash",
            prefix="asitem_",
        )


@dataclass(frozen=True, slots=True)
class RejectedScalingItem:
    schema_version: str
    item_id: str
    item_content_hash: str
    symbol: str
    sizing_result_id: str
    rejection_id: str

    def __post_init__(self) -> None:
        if self.schema_version != REJECTED_SCALING_ITEM_SCHEMA_VERSION:
            raise ValueError("unsupported rejected scaling item schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported scaling symbol")
        require_nonempty_string(self.sizing_result_id, "sizing_result_id")
        require_nonempty_string(self.rejection_id, "rejection_id")
        verify_formal_identity(
            self,
            id_field="item_id",
            hash_field="item_content_hash",
            prefix="rsitem_",
        )


ScalingItem: TypeAlias = AcceptedScalingItem | RejectedScalingItem


@dataclass(frozen=True, slots=True)
class PortfolioScalingResult:
    schema_version: str
    result_id: str
    result_content_hash: str
    portfolio_planning_batch_id: str
    portfolio_planning_batch_content_hash: str
    eligible_time_utc_ms: int
    account_snapshot_id: str
    account_snapshot_hash: str
    ordered_input_result_ids: tuple[str, ...]
    remaining_risk: Decimal
    deployable_cash: Decimal
    risk_scale: Decimal
    cash_scale: Decimal
    final_scale: Decimal
    item_results: tuple[ScalingItem, ...]
    scaling_model_version: str

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_SCALING_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported portfolio scaling result schema")
        require_nonempty_string(self.portfolio_planning_batch_id, "batch ID")
        require_sha256(self.portfolio_planning_batch_content_hash, "batch hash")
        require_utc_ms(self.eligible_time_utc_ms, "eligible_time_utc_ms")
        require_nonempty_string(self.account_snapshot_id, "account_snapshot_id")
        require_sha256(self.account_snapshot_hash, "account_snapshot_hash")
        for name in (
            "remaining_risk",
            "deployable_cash",
            "risk_scale",
            "cash_scale",
            "final_scale",
        ):
            _decimal(getattr(self, name), name)
        if self.final_scale != min(Decimal("1"), self.risk_scale, self.cash_scale):
            raise ValueError("final scale contradicts frozen min formula")
        if self.final_scale > 1:
            raise ValueError("final scale exceeds one")
        expected_order = tuple(
            sorted(
                self.item_results,
                key=lambda item: (item.symbol, item.sizing_result_id, item.item_id),
            )
        )
        if self.item_results != expected_order:
            raise ValueError("scaling items are not canonically ordered")
        if self.scaling_model_version != PORTFOLIO_SCALING_MODEL_VERSION:
            raise ValueError("unsupported scaling model")
        verify_formal_identity(
            self,
            id_field="result_id",
            hash_field="result_content_hash",
            prefix="scale_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def accepted_scaling_item(payload: dict[str, object]) -> AcceptedScalingItem:
    item_id, digest = formal_identity("asitem_", payload)
    return AcceptedScalingItem(item_id=item_id, item_content_hash=digest, **payload)


def rejected_scaling_item(payload: dict[str, object]) -> RejectedScalingItem:
    item_id, digest = formal_identity("rsitem_", payload)
    return RejectedScalingItem(item_id=item_id, item_content_hash=digest, **payload)


def portfolio_scaling_result(payload: dict[str, object]) -> PortfolioScalingResult:
    result_id, digest = formal_identity("scale_", payload)
    return PortfolioScalingResult(result_id=result_id, result_content_hash=digest, **payload)
