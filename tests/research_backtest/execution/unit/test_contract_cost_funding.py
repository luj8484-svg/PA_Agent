from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.contracts import (
    ContractRuleExpiredError,
    ContractRuleUnavailableError,
    approximated_contract_rule,
    ensure_contract_usable,
    unavailable_contract_rule,
    verified_contract_rule,
)
from pa_agent.research_backtest.domain.costs import cost_model_snapshot, exit_fee_reserve
from pa_agent.research_backtest.domain.enums import (
    ApproximationDirection,
    ContractRuleReviewStatus,
    ResearchStage,
)
from pa_agent.research_backtest.domain.funding import (
    FundingRiskConfigUnavailableError,
    FundingScheduleUnverifiedError,
    covered_funding_risk_config,
    funding_schedule_snapshot,
    settlement_window,
    unavailable_funding_risk_config,
)
from pa_agent.research_backtest.planning.funding import (
    count_funding_events,
    effective_adverse_rate_cap,
    funding_reserve,
)
from tests.research_backtest.execution.fixtures.reference_funding import (
    reference_count_funding_windows,
)

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
HOUR = 3_600_000
TARGET = 10 * HOUR


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        function = pytest.mark.requirement_ids(requirement_id)(function)
        return pytest.mark.test_id(test_id)(function)

    return decorate


def verified(*, query: int = TARGET, start: int = 0, end: int = 20 * HOUR):
    return verified_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=query,
        source_kind="BINANCE_ARCHIVE",
        source_uri_or_archive_id="rules/btc/v1",
        source_content_hash=SHA,
        effective_from_utc_ms=start,
        effective_to_utc_ms=end,
        rule_version="BTCUSDT_RULE_V1",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="d" * 64,
    )


def prior_approx(*, evidence_time: int = TARGET - 1):
    return approximated_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET,
        source_kind="REVIEWED_ARCHIVE",
        source_uri_or_archive_id="rules/btc/prior",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=20 * HOUR,
        rule_version="BTCUSDT_APPROX_V1",
        review_status=ContractRuleReviewStatus.APPROVED_PRIOR_ONLY,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="d" * 64,
        approximation_method="NEAREST_PRIOR_REVIEWED_RULE",
        approximation_distance_ms=abs(TARGET - evidence_time),
        evidence_time_utc_ms=evidence_time,
        approximation_direction=ApproximationDirection.PRIOR_ONLY_APPROXIMATION,
    )


def schedule(
    *,
    windows: tuple[tuple[int, int, int], ...] | None = None,
    effective_from: int = 0,
    effective_to: int = 100 * HOUR,
):
    raw = windows or (
        (8 * HOUR - 1_000, 8 * HOUR, 8 * HOUR + 1_000),
        (16 * HOUR - 1_000, 16 * HOUR, 16 * HOUR + 1_000),
    )
    return funding_schedule_snapshot(
        symbol="BTCUSDT",
        schedule_version="BINANCE_EXPLICIT_WINDOWS_V1",
        effective_from_utc_ms=effective_from,
        effective_to_utc_ms=effective_to,
        settlement_windows=tuple(settlement_window(*row) for row in raw),
        window_tolerance_ms=1_000,
        source_manifest_hash=SHA,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


def risk_config(*, stress: Decimal = Decimal("1"), evidence_time: int = TARGET):
    return covered_funding_risk_config(
        symbol="BTCUSDT",
        target_time_utc_ms=TARGET,
        adverse_rate_cap=Decimal("0.0001"),
        effective_from_utc_ms=0,
        effective_to_utc_ms=20 * HOUR,
        source_kind="BASELINE_RESEARCH_ASSUMPTION",
        source_manifest_hash=SHA,
        verification_mode="APPROXIMATED",
        stress_multiplier=stress,
        watermark="BASELINE_ASSUMPTION_NOT_VERIFIED",
        evidence_time_utc_ms=evidence_time,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


@registered("UT-SCHEMA-006", "2B-SCHEMA-006")
def test_contract_modes_are_distinct_closed_types() -> None:
    assert type(verified()).__name__ == "VerifiedContractRuleCoverage"
    assert type(prior_approx()).__name__ == "ApproximatedContractRuleCoverage"
    assert (
        type(
            unavailable_contract_rule(
                symbol="BTCUSDT",
                query_time_utc_ms=TARGET,
                unavailable_reason="ARCHIVE_NOT_FOUND",
                searched_archive_hashes=(),
            )
        ).__name__
        == "UnavailableContractRuleCoverage"
    )


@registered("UT-SCHEMA-014", "2B-SCHEMA-014")
def test_funding_risk_config_is_separate_from_schedule() -> None:
    assert not hasattr(schedule(), "adverse_rate_cap")
    assert not hasattr(risk_config(), "settlement_windows")


@registered("UT-TIME-005", "2B-TIME-005")
def test_contract_validity_is_half_open() -> None:
    ensure_contract_usable(verified(query=0), ResearchStage.BACKTEST)
    ensure_contract_usable(verified(query=20 * HOUR - 1), ResearchStage.BACKTEST)
    with pytest.raises(ContractRuleExpiredError):
        ensure_contract_usable(verified(query=20 * HOUR), ResearchStage.BACKTEST)


@registered("UT-TIME-010", "2B-TIME-010")
def test_funding_at_maximum_exit_is_counted() -> None:
    value = schedule(windows=((8 * HOUR, 8 * HOUR, 8 * HOUR),))
    assert count_funding_events(0, 8 * HOUR, value) == 1


@registered("UT-TIME-012", "2B-TIME-012")
def test_prior_approximation_never_uses_future_evidence() -> None:
    with pytest.raises(ValueError, match="future evidence"):
        prior_approx(evidence_time=TARGET + 1)


@registered("UT-COST-004", "2B-COST-004")
def test_cost_rates_are_exact_decimal_products() -> None:
    value = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1.5"),
    )
    assert value.effective_fee_rate == Decimal("0.00075")
    assert value.effective_slippage_rate == Decimal("0.00015")


@registered("UT-COST-006", "2B-COST-006")
def test_exit_fee_reserve_uses_frozen_max_envelope() -> None:
    value = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1"),
    )
    assert exit_fee_reserve(
        Decimal("2"), (Decimal("100"), Decimal("110"), Decimal("90")), value
    ) == Decimal("0.11")


@registered("UT-COST-007", "2B-COST-007")
def test_funding_reserve_uses_same_price_envelope() -> None:
    assert funding_reserve(Decimal("2"), Decimal("110"), Decimal("0.0002"), 3) == Decimal("0.1320")


@registered("UT-FUND-001", "2B-FUND-001")
def test_funding_interval_is_open_entry_closed_exit() -> None:
    value = schedule(windows=((8 * HOUR, 8 * HOUR, 8 * HOUR),))
    assert count_funding_events(8 * HOUR, 9 * HOUR, value) == 0
    assert count_funding_events(8 * HOUR - 1, 8 * HOUR, value) == 1


@registered("UT-FUND-002", "2B-FUND-002")
def test_entry_around_window_end_changes_count_by_one() -> None:
    value = schedule(windows=((8 * HOUR - 1_000, 8 * HOUR, 8 * HOUR + 1_000),))
    assert count_funding_events(8 * HOUR + 999, 9 * HOUR, value) == 1
    assert count_funding_events(8 * HOUR + 1_000, 9 * HOUR, value) == 0


@registered("UT-FUND-003", "2B-FUND-003")
def test_exit_endpoint_window_is_inclusive() -> None:
    value = schedule(windows=((12 * HOUR, 12 * HOUR, 12 * HOUR + 1_000),))
    assert count_funding_events(TARGET, 12 * HOUR, value) == 1


@registered("UT-FUND-004", "2B-FUND-004")
def test_irregular_schedule_is_enumerated_without_eight_hour_assumption() -> None:
    windows = tuple((hour * HOUR, hour * HOUR, hour * HOUR) for hour in (6, 12, 24, 27))
    value = schedule(windows=windows)
    assert count_funding_events(0, 30 * HOUR, value) == 4


@registered("UT-FUND-005", "2B-FUND-005")
def test_schedule_must_cover_the_entire_interval() -> None:
    value = schedule(effective_from=1, effective_to=20 * HOUR)
    with pytest.raises(FundingScheduleUnverifiedError):
        count_funding_events(0, 10 * HOUR, value)
    with pytest.raises(FundingScheduleUnverifiedError):
        count_funding_events(10 * HOUR, 20 * HOUR, value)


@registered("UT-FUND-006", "2B-FUND-006")
def test_exact_48h_with_tolerance_can_count_seven_windows() -> None:
    entry = 1_000_000
    windows = tuple(
        (
            entry + index * 8 * HOUR - 1_000,
            entry + index * 8 * HOUR,
            entry + index * 8 * HOUR + 1_000,
        )
        for index in range(7)
    )
    value = schedule(
        windows=windows,
        effective_from=entry - 1_000,
        effective_to=entry + 48 * HOUR + 1_001,
    )
    expected = reference_count_funding_windows(entry, entry + 48 * HOUR, windows)
    assert expected == 7
    assert count_funding_events(entry, entry + 48 * HOUR, value) == expected


@registered("UT-FUND-007", "2B-FUND-007")
def test_funding_risk_config_requires_target_coverage() -> None:
    with pytest.raises(ValueError, match="target coverage"):
        covered_funding_risk_config(
            symbol="BTCUSDT",
            target_time_utc_ms=TARGET,
            adverse_rate_cap=Decimal("0.0001"),
            effective_from_utc_ms=0,
            effective_to_utc_ms=TARGET,
            source_kind="REVIEWED_ARCHIVE",
            source_manifest_hash=SHA,
            verification_mode="VERIFIED",
            stress_multiplier=Decimal("1"),
            watermark="VERIFIED",
            evidence_time_utc_ms=TARGET,
            code_commit=COMMIT,
            dependency_lock_hash=LOCK,
        )


@registered("UT-FUND-008", "2B-FUND-008")
def test_baseline_cap_requires_explicit_approximation_watermark() -> None:
    value = risk_config()
    assert value.adverse_rate_cap == Decimal("0.0001")
    assert value.watermark == "BASELINE_ASSUMPTION_NOT_VERIFIED"
    with pytest.raises(ValueError, match="watermark"):
        replace(value, watermark="VERIFIED")


@registered("UT-FUND-009", "2B-FUND-009")
def test_funding_stress_is_independent_and_monotonic() -> None:
    assert [
        effective_adverse_rate_cap(risk_config(stress=value))
        for value in (Decimal("1"), Decimal("1.5"), Decimal("2"))
    ] == [Decimal("0.0001"), Decimal("0.00015"), Decimal("0.0002")]


@registered("UT-RULE-001", "2B-RULE-001")
def test_verified_contract_rule_is_usable_when_covered() -> None:
    assert ensure_contract_usable(verified(), ResearchStage.BACKTEST).mode.value == "VERIFIED"


@registered("UT-RULE-002", "2B-RULE-002")
def test_approximated_rule_carries_direction_and_watermark() -> None:
    value = prior_approx()
    assert value.approximation_direction is ApproximationDirection.PRIOR_ONLY_APPROXIMATION
    assert value.approximation_watermark == "APPROXIMATED_NOT_LIVE_ELIGIBLE"


@registered("UT-RULE-003", "2B-RULE-003")
def test_hindsight_is_diagnostic_only_and_approx_is_never_live_eligible() -> None:
    hindsight = approximated_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET,
        source_kind="REVIEWED_ARCHIVE",
        source_uri_or_archive_id="future",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=20 * HOUR,
        rule_version="HINDSIGHT_V1",
        review_status=ContractRuleReviewStatus.APPROVED_HINDSIGHT_DIAGNOSTIC,
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0"),
        min_notional=Decimal("0"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="d" * 64,
        approximation_method="FUTURE_DIAGNOSTIC",
        approximation_distance_ms=1,
        evidence_time_utc_ms=TARGET + 1,
        approximation_direction=ApproximationDirection.HINDSIGHT_DIAGNOSTIC_APPROXIMATION,
    )
    ensure_contract_usable(hindsight, ResearchStage.BACKTEST)
    with pytest.raises(ValueError, match="diagnostic"):
        ensure_contract_usable(hindsight, ResearchStage.PAPER_SIMULATION)
    with pytest.raises(ValueError, match="live"):
        ensure_contract_usable(prior_approx(), ResearchStage.LIVE_ELIGIBILITY_RESEARCH)


@registered("UT-RULE-004", "2B-RULE-004")
def test_unavailable_contract_rule_never_becomes_a_plan_input() -> None:
    value = unavailable_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET,
        unavailable_reason="ARCHIVE_NOT_FOUND",
        searched_archive_hashes=(),
    )
    with pytest.raises(ContractRuleUnavailableError):
        ensure_contract_usable(value, ResearchStage.BACKTEST)


@registered("UT-RULE-005", "2B-RULE-005")
def test_contract_tick_step_and_minimum_values_are_validated() -> None:
    with pytest.raises(ValueError, match="tick"):
        replace(verified(), tick_size=Decimal("0"))
    with pytest.raises(ValueError, match="minimum"):
        replace(verified(), min_notional=Decimal("-1"))


@registered("UT-RULE-006", "2B-RULE-006")
def test_rule_version_changes_contract_identity() -> None:
    original = verified()
    changed = verified_contract_rule(
        symbol=original.symbol,
        query_time_utc_ms=original.query_time_utc_ms,
        source_kind=original.source_kind,
        source_uri_or_archive_id=original.source_uri_or_archive_id,
        source_content_hash=original.source_content_hash,
        effective_from_utc_ms=original.effective_from_utc_ms,
        effective_to_utc_ms=original.effective_to_utc_ms,
        rule_version="BTCUSDT_RULE_V2",
        tick_size=original.tick_size,
        step_size=original.step_size,
        min_qty=original.min_qty,
        min_notional=original.min_notional,
        quantity_precision_audit=original.quantity_precision_audit,
        price_precision_audit=original.price_precision_audit,
        evidence_manifest_hash=original.evidence_manifest_hash,
    )
    assert changed.coverage_id != original.coverage_id


@registered("UT-RULE-007", "2B-RULE-007")
def test_contract_and_cost_hashes_self_verify() -> None:
    with pytest.raises(ValueError, match="content"):
        replace(verified(), source_content_hash="f" * 64)
    value = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1"),
    )
    with pytest.raises(ValueError, match=r"formula|content"):
        replace(value, fee_rate=Decimal("0.0004"))


@registered("UT-RULE-008", "2B-RULE-008")
def test_prior_only_is_the_only_primary_approximation() -> None:
    ensure_contract_usable(prior_approx(), ResearchStage.PAPER_SIMULATION)


@registered("UT-RULE-009", "2B-RULE-009")
def test_review_status_is_a_frozen_enum() -> None:
    with pytest.raises(ValueError, match="review"):
        replace(prior_approx(), review_status="APPROVED_SOMETHING_ELSE")


@registered("PT-FUND-RISK-COVERAGE", "2B-FUND-007")
def test_unavailable_funding_risk_is_a_distinct_type() -> None:
    value = unavailable_funding_risk_config(
        symbol="BTCUSDT",
        target_time_utc_ms=TARGET,
        watermark="FUNDING_RISK_CONFIG_UNAVAILABLE",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    with pytest.raises(FundingRiskConfigUnavailableError):
        effective_adverse_rate_cap(value)
