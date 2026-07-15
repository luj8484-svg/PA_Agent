from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.funding import (
    SETTLEMENT_BOUNDARY_SEMANTICS,
    CoveredFundingRiskConfigSnapshot,
    FundingRiskConfigSnapshot,
    FundingRiskConfigUnavailableError,
    FundingScheduleSnapshot,
    FundingScheduleUnverifiedError,
    UnavailableFundingRiskConfigSnapshot,
)


def count_funding_events(
    entry_time_utc_ms: int,
    maximum_exit_time_utc_ms: int,
    schedule: FundingScheduleSnapshot,
    settlement_boundary_semantics: str = SETTLEMENT_BOUNDARY_SEMANTICS,
) -> int:
    if settlement_boundary_semantics != SETTLEMENT_BOUNDARY_SEMANTICS:
        raise FundingScheduleUnverifiedError("unsupported settlement boundary semantics")
    if type(entry_time_utc_ms) is not int or type(maximum_exit_time_utc_ms) is not int:
        raise FundingScheduleUnverifiedError("funding interval must use integer UTC milliseconds")
    if entry_time_utc_ms < 0 or maximum_exit_time_utc_ms < entry_time_utc_ms:
        raise FundingScheduleUnverifiedError("invalid funding count interval")
    if schedule.effective_from_utc_ms > entry_time_utc_ms:
        raise FundingScheduleUnverifiedError("funding schedule does not cover entry")
    if maximum_exit_time_utc_ms >= schedule.effective_to_utc_ms:
        raise FundingScheduleUnverifiedError("funding schedule does not cover maximum exit")
    return sum(
        window.window_end_utc_ms > entry_time_utc_ms
        and window.window_start_utc_ms <= maximum_exit_time_utc_ms
        for window in schedule.settlement_windows
    )


def effective_adverse_rate_cap(config: FundingRiskConfigSnapshot) -> Decimal:
    if isinstance(config, UnavailableFundingRiskConfigSnapshot):
        raise FundingRiskConfigUnavailableError("funding risk config is unavailable")
    if not isinstance(config, CoveredFundingRiskConfigSnapshot):
        raise TypeError("unsupported funding risk config")
    return config.adverse_rate_cap * config.stress_multiplier


def funding_reserve(
    quantity: Decimal,
    funding_notional_price_basis: Decimal,
    effective_rate_cap: Decimal,
    event_count: int,
) -> Decimal:
    values = (quantity, funding_notional_price_basis, effective_rate_cap)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise ValueError("funding reserve requires finite Decimal inputs")
    if quantity < 0 or funding_notional_price_basis <= 0 or effective_rate_cap < 0:
        raise ValueError("funding reserve inputs violate their domains")
    if type(event_count) is not int or event_count < 0:
        raise ValueError("funding event count must be nonnegative integer")
    return quantity * funding_notional_price_basis * effective_rate_cap * event_count
