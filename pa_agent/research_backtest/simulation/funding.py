from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from pa_agent.research_backtest.domain.base import require_sha256
from pa_agent.research_backtest.domain.enums import Side
from pa_agent.research_backtest.simulation.positions import IsolatedPosition


@dataclass(frozen=True, slots=True)
class FundingRecord:
    record_id: str
    symbol: str
    funding_time_utc_ms: int
    funding_rate: Decimal
    mark_price: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        if not self.record_id or self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("invalid funding record identity")
        if type(self.funding_time_utc_ms) is not int or self.funding_time_utc_ms < 0:
            raise ValueError("invalid funding time")
        for name in ("funding_rate", "mark_price"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be finite Decimal")
        if self.mark_price <= 0:
            raise ValueError("funding mark price must be positive")
        require_sha256(self.content_hash, "funding content_hash")


@dataclass(frozen=True, slots=True)
class FundingSettlement:
    obligation_id: str
    position_id: str
    funding_record_id: str
    event_time_utc_ms: int
    wallet_delta: Decimal
    reserve_release: Decimal


@dataclass(frozen=True, slots=True)
class FundingReserveExceeded:
    event_time_utc_ms: int
    position_id: str
    funding_record_id: str
    actual_adverse_payment: Decimal
    remaining_reserve: Decimal
    reason: str = "FUNDING_RESERVE_EXCEEDED"


def settle_funding(
    position: IsolatedPosition, record: FundingRecord
) -> FundingSettlement | FundingReserveExceeded:
    if position.symbol != record.symbol:
        raise ValueError("funding symbol does not match position symbol")
    side_sign = Decimal("1") if position.side is Side.LONG else Decimal("-1")
    notional = position.quantity * record.mark_price
    wallet_delta = -(side_sign * notional * record.funding_rate)
    if wallet_delta < 0 and abs(wallet_delta) > position.remaining_funding_reserve:
        return FundingReserveExceeded(
            event_time_utc_ms=record.funding_time_utc_ms,
            position_id=position.position_id,
            funding_record_id=record.record_id,
            actual_adverse_payment=abs(wallet_delta),
            remaining_reserve=position.remaining_funding_reserve,
        )
    release = min(position.planned_funding_slice, position.remaining_funding_reserve)
    return FundingSettlement(
        obligation_id=f"{position.position_id}:{record.record_id}",
        position_id=position.position_id,
        funding_record_id=record.record_id,
        event_time_utc_ms=record.funding_time_utc_ms,
        wallet_delta=wallet_delta,
        reserve_release=release,
    )


def apply_funding_to_position(
    position: IsolatedPosition, settlement: FundingSettlement
) -> IsolatedPosition:
    if settlement.position_id != position.position_id:
        raise ValueError("funding settlement position does not match")
    if position.remaining_funding_events <= 0:
        raise ValueError("funding schedule has no remaining event")
    return replace(
        position,
        remaining_funding_reserve=(position.remaining_funding_reserve - settlement.reserve_release),
        remaining_funding_events=position.remaining_funding_events - 1,
        funding_wallet_delta_sum=(position.funding_wallet_delta_sum + settlement.wallet_delta),
    )
