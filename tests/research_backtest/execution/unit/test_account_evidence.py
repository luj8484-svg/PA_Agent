from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.accounts import (
    RequiredAccountEvidenceUnavailableError,
    account_evidence_bundle,
    account_evidence_records,
    experiment_state_evidence,
    make_account_planning_snapshot,
    open_risk_evidence,
    pending_plan_evidence,
    position_evidence,
    replay_account_evidence,
    valuation_evidence,
    wallet_ledger_evidence,
)
from tests.research_backtest.execution.fixtures.reference_account import (
    reference_account_aggregates,
)

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
ELIGIBLE = 20_000_000


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        function = pytest.mark.requirement_ids(requirement_id)(function)
        return pytest.mark.test_id(test_id)(function)

    return decorate


def records(*, pending_reserve: Decimal = Decimal("100"), include_risk: bool = True):
    risk_records = (
        (open_risk_evidence(symbol="BTCUSDT", risk=Decimal("40")),) if include_risk else ()
    )
    return account_evidence_records(
        wallet=wallet_ledger_evidence(
            wallet_balance=Decimal("10000"),
            locked_initial_margin=Decimal("1000"),
            locked_fee_reserve=Decimal("10"),
            locked_funding_reserve=Decimal("5"),
        ),
        valuations=(
            valuation_evidence(
                symbol="BTCUSDT",
                event_time_utc_ms=ELIGIBLE,
                unrealized_pnl=Decimal("-50"),
            ),
        ),
        positions=(position_evidence(symbol="BTCUSDT"),),
        open_risks=risk_records,
        pending_plans=(
            pending_plan_evidence(
                symbol="ETHUSDT",
                planned_risk=Decimal("20"),
                required_reserve=pending_reserve,
            ),
        ),
        experiment_state=experiment_state_evidence(
            event_time_utc_ms=ELIGIBLE,
            state="RUNNING",
        ),
    )


def bundle(*, pending_reserve: Decimal = Decimal("100"), include_risk: bool = True):
    evidence = records(pending_reserve=pending_reserve, include_risk=include_risk)
    return (
        account_evidence_bundle(
            evidence,
            event_time_utc_ms=ELIGIBLE,
            code_commit=COMMIT,
            dependency_lock_hash=LOCK,
        ),
        evidence,
    )


@registered("UT-SCHEMA-015", "2B-SCHEMA-015")
def test_account_snapshot_is_a_read_only_planning_view() -> None:
    value, evidence = bundle()
    snapshot = make_account_planning_snapshot(value, evidence, eligible_time_utc_ms=ELIGIBLE)
    assert snapshot.wallet_balance == Decimal("10000")
    assert snapshot.existing_position_symbols == ("BTCUSDT",)
    with pytest.raises(AttributeError):
        snapshot.wallet_balance = Decimal("0")


@registered("UT-SCHEMA-020", "2B-SCHEMA-020")
def test_account_bundle_is_closed_and_naked_hashes_are_not_evidence() -> None:
    value, _ = bundle()
    names = {field.name for field in fields(type(value))}
    assert {"bundle_id", "bundle_content_hash", "valuation_snapshot_ids"} <= names
    with pytest.raises(RequiredAccountEvidenceUnavailableError):
        replay_account_evidence(value, None)


@registered("UT-TIME-015", "2B-TIME-015")
def test_valuation_evidence_must_match_eligible_time_and_frozen_basis() -> None:
    value, evidence = bundle()
    with pytest.raises(ValueError, match="eligible time"):
        make_account_planning_snapshot(value, evidence, eligible_time_utc_ms=ELIGIBLE + 1)
    stale = valuation_evidence(
        symbol="BTCUSDT",
        event_time_utc_ms=ELIGIBLE - 1,
        unrealized_pnl=Decimal("-50"),
    )
    with pytest.raises(ValueError):
        account_evidence_records(
            wallet=evidence.wallet,
            valuations=(stale,),
            positions=evidence.positions,
            open_risks=evidence.open_risks,
            pending_plans=evidence.pending_plans,
            experiment_state=evidence.experiment_state,
        )


@registered("UT-RISK-006", "2B-RISK-006")
def test_snapshot_matches_independent_account_reference() -> None:
    value, evidence = bundle()
    aggregates = replay_account_evidence(value, evidence)
    expected = reference_account_aggregates(
        wallet_balance=Decimal("10000"),
        locked_initial_margin=Decimal("1000"),
        locked_fee_reserve=Decimal("10"),
        locked_funding_reserve=Decimal("5"),
        valuation_pnls=(Decimal("-50"),),
        open_risks=(Decimal("40"),),
        pending_risks=(Decimal("20"),),
        pending_reserves=(Decimal("100"),),
    )
    assert (
        aggregates.current_equity,
        aggregates.available_balance,
        aggregates.existing_open_risk,
        aggregates.pending_plan_risk,
        aggregates.pending_plan_reserve,
    ) == expected


@registered("UT-RISK-007", "2B-RISK-007")
def test_pending_reserve_cannot_exceed_available_balance() -> None:
    with pytest.raises(ValueError, match="pending reserve"):
        bundle(pending_reserve=Decimal("9000"))


@registered("UT-RISK-010", "2B-RISK-010")
def test_missing_open_risk_records_are_not_silently_downgraded() -> None:
    with pytest.raises(RequiredAccountEvidenceUnavailableError, match="open-risk"):
        bundle(include_risk=False)


@registered("UT-RISK-011", "2B-RISK-011")
def test_current_equity_is_replayed_from_wallet_and_unrealized_pnl() -> None:
    value, evidence = bundle()
    assert value.current_equity == Decimal("9950")
    with pytest.raises(ValueError):
        replace(value, current_equity=Decimal("9951"))
    assert replay_account_evidence(value, evidence).current_equity == Decimal("9950")


@registered("UT-RISK-012", "2B-RISK-012")
def test_open_risk_and_pending_aggregates_replay_from_record_sets() -> None:
    value, evidence = bundle()
    assert value.existing_open_risk == Decimal("40")
    assert value.pending_plan_risk == Decimal("20")
    with pytest.raises(ValueError):
        replace(value, pending_plan_risk=Decimal("21"))
    changed = pending_plan_evidence(
        symbol="ETHUSDT",
        planned_risk=Decimal("21"),
        required_reserve=Decimal("100"),
    )
    changed_records = account_evidence_records(
        wallet=evidence.wallet,
        valuations=evidence.valuations,
        positions=evidence.positions,
        open_risks=evidence.open_risks,
        pending_plans=(changed,),
        experiment_state=evidence.experiment_state,
    )
    with pytest.raises(ValueError, match="does not match"):
        replay_account_evidence(value, changed_records)
