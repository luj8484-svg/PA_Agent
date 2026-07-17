from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import require_sha256
from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
from pa_agent.research_backtest.simulation.positions import IsolatedPosition
from pa_agent.research_backtest.simulation.versions import (
    LIQUIDATION_MODEL_VERSION,
    LIQUIDATION_WATERMARK,
)


@dataclass(frozen=True, slots=True)
class MaintenanceEvidence:
    symbol: str
    effective_start_utc_ms: int
    effective_end_utc_ms: int
    notional_floor: Decimal
    notional_cap: Decimal
    maintenance_margin_rate: Decimal
    source_hash: str
    mode: str
    version: str

    def __post_init__(self) -> None:
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported maintenance symbol")
        if (
            type(self.effective_start_utc_ms) is not int
            or type(self.effective_end_utc_ms) is not int
            or self.effective_end_utc_ms <= self.effective_start_utc_ms
        ):
            raise ValueError("invalid maintenance effective interval")
        for name in ("notional_floor", "notional_cap", "maintenance_margin_rate"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be finite Decimal")
        if not (Decimal("0") <= self.maintenance_margin_rate < Decimal("1")):
            raise ValueError("maintenance rate must be in [0,1)")
        if self.notional_floor < 0 or self.notional_cap <= self.notional_floor:
            raise ValueError("invalid maintenance notional tier")
        if self.mode not in {"VERIFIED", "APPROXIMATED"}:
            raise ValueError("maintenance mode must be verified or approximated")
        require_sha256(self.source_hash, "maintenance source_hash")


@dataclass(frozen=True, slots=True)
class LiquidationReference:
    position_id: str
    liquidation_price: Decimal
    maintenance_margin_rate: Decimal
    maintenance_source_hash: str
    maintenance_version: str
    maintenance_mode: str
    model_version: str = LIQUIDATION_MODEL_VERSION
    watermark: str = LIQUIDATION_WATERMARK


def estimated_liquidation(
    position: IsolatedPosition,
    evidence: MaintenanceEvidence | None,
    event_time_utc_ms: int,
) -> LiquidationReference | PathInvalidEvent:
    if evidence is None:
        return PathInvalidEvent(event_time_utc_ms, "MAINTENANCE_EVIDENCE_UNAVAILABLE")
    notional = position.quantity * position.entry_price
    usable = (
        position.symbol == evidence.symbol
        and evidence.effective_start_utc_ms <= event_time_utc_ms < evidence.effective_end_utc_ms
        and evidence.notional_floor <= notional < evidence.notional_cap
    )
    if not usable:
        return PathInvalidEvent(event_time_utc_ms, "MAINTENANCE_EVIDENCE_UNAVAILABLE")
    q = position.quantity
    price = position.entry_price
    margin = position.isolated_margin_balance
    rate = evidence.maintenance_margin_rate
    if position.side is Side.LONG:
        liquidation = max(Decimal("0"), (q * price - margin) / (q * (1 - rate)))
    else:
        liquidation = (margin + q * price) / (q * (1 + rate))
    return LiquidationReference(
        position_id=position.position_id,
        liquidation_price=liquidation,
        maintenance_margin_rate=rate,
        maintenance_source_hash=evidence.source_hash,
        maintenance_version=evidence.version,
        maintenance_mode=evidence.mode,
    )
