from dataclasses import replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.enums import Side


def position(side: Side = Side.LONG):
    from pa_agent.research_backtest.simulation.positions import IsolatedPosition

    return IsolatedPosition(
        position_id="pos-1",
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal("2"),
        entry_time_utc_ms=0,
        entry_price=Decimal("100"),
        initial_margin=Decimal("200"),
        isolated_margin_balance=Decimal("200"),
        stop_trigger_price=Decimal("90"),
        take_profit_trigger_price=Decimal("120"),
        remaining_fee_reserve=Decimal("1"),
        remaining_funding_reserve=Decimal("6"),
        planned_funding_slice=Decimal("2"),
        remaining_funding_events=3,
        origin_plan_id="plan-1",
        origin_candidate_id="candidate-1",
        maximum_exit_time_utc_ms=172_800_000,
    )


def funding(rate: str):
    from pa_agent.research_backtest.simulation.funding import FundingRecord

    return FundingRecord(
        record_id="fund-1",
        symbol="BTCUSDT",
        funding_time_utc_ms=60_000,
        funding_rate=Decimal(rate),
        mark_price=Decimal("100"),
        content_hash="a" * 64,
    )


@pytest.mark.parametrize(
    ("side", "rate", "expected"),
    [
        (Side.LONG, "0.01", "-2"),
        (Side.LONG, "-0.01", "2"),
        (Side.SHORT, "0.01", "2"),
        (Side.SHORT, "-0.01", "-2"),
    ],
)
def test_funding_sign_quadrants(side: Side, rate: str, expected: str) -> None:
    from pa_agent.research_backtest.simulation.funding import FundingSettlement, settle_funding

    result = settle_funding(position(side), funding(rate))
    assert isinstance(result, FundingSettlement)
    assert result.wallet_delta == Decimal(expected)
    assert result.reserve_release == Decimal("2")


def test_funding_income_does_not_increase_reserve() -> None:
    from pa_agent.research_backtest.simulation.funding import (
        apply_funding_to_position,
        settle_funding,
    )

    updated = apply_funding_to_position(position(), settle_funding(position(), funding("-0.01")))
    assert updated.remaining_funding_reserve == Decimal("4")
    assert updated.isolated_margin_balance == Decimal("200")


def test_funding_payment_over_remaining_reserve_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.funding import FundingReserveExceeded, settle_funding

    tiny = replace(position(), remaining_funding_reserve=Decimal("1"))
    result = settle_funding(tiny, funding("0.01"))
    assert isinstance(result, FundingReserveExceeded)
    assert result.reason == "FUNDING_RESERVE_EXCEEDED"
    assert result.funding_record_id == "fund-1"


def test_funding_symbol_mismatch_fails_closed() -> None:
    from pa_agent.research_backtest.simulation.funding import settle_funding

    with pytest.raises(ValueError, match="symbol"):
        settle_funding(replace(position(), symbol="ETHUSDT"), funding("0.01"))


def maintenance(rate: str = "0.005"):
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence

    return MaintenanceEvidence(
        symbol="BTCUSDT",
        effective_start_utc_ms=0,
        effective_end_utc_ms=120_000,
        notional_floor=Decimal("0"),
        notional_cap=Decimal("1000000"),
        maintenance_margin_rate=Decimal(rate),
        source_hash="b" * 64,
        mode="APPROXIMATED",
        version="MMR_V1",
    )


def test_long_liquidation_uses_fixed_isolated_margin_reference() -> None:
    from pa_agent.research_backtest.simulation.liquidation import estimated_liquidation

    result = estimated_liquidation(position(Side.LONG), maintenance(), 60_000)
    expected = (Decimal("200") - Decimal("200")) / (Decimal("2") * Decimal("0.995"))
    assert result.liquidation_price == expected
    assert result.model_version == "ESTIMATED_FIXED_ISOLATED_MARGIN_V1"
    assert result.watermark == "ESTIMATED_NOT_EXCHANGE_EXACT"


def test_short_liquidation_formula() -> None:
    from pa_agent.research_backtest.simulation.liquidation import estimated_liquidation

    result = estimated_liquidation(position(Side.SHORT), maintenance(), 60_000)
    expected = Decimal("400") / (Decimal("2") * Decimal("1.005"))
    assert result.liquidation_price == expected


def test_maintenance_expired_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
    from pa_agent.research_backtest.simulation.liquidation import estimated_liquidation

    result = estimated_liquidation(position(), maintenance(), 180_000)
    assert isinstance(result, PathInvalidEvent)
    assert result.reason == "MAINTENANCE_EVIDENCE_UNAVAILABLE"


def test_fees_and_funding_never_change_isolated_margin() -> None:
    from pa_agent.research_backtest.simulation.funding import (
        apply_funding_to_position,
        settle_funding,
    )

    original = position()
    updated = apply_funding_to_position(original, settle_funding(original, funding("0.01")))
    assert updated.isolated_margin_balance == original.initial_margin
