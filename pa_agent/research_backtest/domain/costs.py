from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import formal_identity, verify_formal_identity
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.versions import (
    COST_MODEL_SNAPSHOT_SCHEMA_VERSION,
    FEE_MODEL_VERSION,
    FUNDING_BUFFER_MODEL_VERSION,
    SLIPPAGE_MODEL_VERSION,
)


def _rate(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite nonnegative Decimal")


@dataclass(frozen=True, slots=True)
class CostModelSnapshot:
    schema_version: str
    snapshot_id: str
    snapshot_content_hash: str
    symbol: str
    fee_rate: Decimal
    slippage_rate: Decimal
    stress_multiplier: Decimal
    effective_fee_rate: Decimal
    effective_slippage_rate: Decimal
    fee_model_version: str
    slippage_model_version: str
    funding_buffer_model_version: str

    def __post_init__(self) -> None:
        if self.schema_version != COST_MODEL_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported cost model schema")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported cost model symbol")
        _rate(self.fee_rate, "fee_rate")
        _rate(self.slippage_rate, "slippage_rate")
        if self.stress_multiplier not in {Decimal("1"), Decimal("1.5"), Decimal("2")}:
            raise ValueError("cost stress multiplier must be 1, 1.5, or 2")
        if self.effective_fee_rate != self.fee_rate * self.stress_multiplier:
            raise ValueError("effective fee rate contradicts the frozen formula")
        if self.effective_slippage_rate != self.slippage_rate * self.stress_multiplier:
            raise ValueError("effective slippage rate contradicts the frozen formula")
        if self.fee_model_version != FEE_MODEL_VERSION:
            raise ValueError("unsupported fee model")
        if self.slippage_model_version != SLIPPAGE_MODEL_VERSION:
            raise ValueError("unsupported slippage model")
        if self.funding_buffer_model_version != FUNDING_BUFFER_MODEL_VERSION:
            raise ValueError("unsupported funding buffer model")
        verify_formal_identity(
            self,
            id_field="snapshot_id",
            hash_field="snapshot_content_hash",
            prefix="cost_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def cost_model_snapshot(
    *,
    symbol: str,
    fee_rate: Decimal,
    slippage_rate: Decimal,
    stress_multiplier: Decimal,
) -> CostModelSnapshot:
    payload = {
        "schema_version": COST_MODEL_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "stress_multiplier": stress_multiplier,
        "effective_fee_rate": fee_rate * stress_multiplier,
        "effective_slippage_rate": slippage_rate * stress_multiplier,
        "fee_model_version": FEE_MODEL_VERSION,
        "slippage_model_version": SLIPPAGE_MODEL_VERSION,
        "funding_buffer_model_version": FUNDING_BUFFER_MODEL_VERSION,
    }
    snapshot_id, digest = formal_identity("cost_", payload)
    return CostModelSnapshot(
        snapshot_id=snapshot_id,
        snapshot_content_hash=digest,
        **payload,
    )


def exit_fee_reserve(
    quantity: Decimal,
    price_envelope: tuple[Decimal, Decimal, Decimal],
    cost: CostModelSnapshot,
) -> Decimal:
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
        raise ValueError("quantity must be finite nonnegative Decimal")
    if any(not value.is_finite() or value <= 0 for value in price_envelope):
        raise ValueError("price envelope must contain positive finite Decimal values")
    return quantity * max(price_envelope) * cost.effective_fee_rate
