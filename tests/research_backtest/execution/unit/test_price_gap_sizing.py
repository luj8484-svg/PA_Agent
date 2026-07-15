from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.accounts import (
    account_evidence_bundle,
    account_evidence_records,
    experiment_state_evidence,
    make_account_planning_snapshot,
    wallet_ledger_evidence,
)
from pa_agent.research_backtest.domain.contracts import verified_contract_rule
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ResearchStage,
    Side,
)
from pa_agent.research_backtest.domain.funding import covered_funding_risk_config
from pa_agent.research_backtest.domain.rejections import entry_intent_subject_ref_from_identity
from pa_agent.research_backtest.domain.sizing import SizingRejected
from pa_agent.research_backtest.planning.prices import (
    PriceGeometryInvalid,
    adverse_gap,
    price_geometry,
)
from pa_agent.research_backtest.planning.sizing import SizingInputs, position_sizing
from tests.research_backtest.execution.fixtures.reference_decimal_formulas import (
    reference_prices,
    reference_sizing,
)

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
TARGET = 20_000_000


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        function = pytest.mark.requirement_ids(requirement_id)(function)
        return pytest.mark.test_id(test_id)(function)

    return decorate


def contract(*, min_qty=Decimal("0.001"), min_notional=Decimal("5")):
    return verified_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET,
        source_kind="ARCHIVE",
        source_uri_or_archive_id="rules",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=TARGET + 1,
        rule_version="RULE_V1",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=min_qty,
        min_notional=min_notional,
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="d" * 64,
    )


def cost(*, stress=Decimal("1")):
    return cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=stress,
    )


def funding():
    return covered_funding_risk_config(
        symbol="BTCUSDT",
        target_time_utc_ms=TARGET,
        adverse_rate_cap=Decimal("0.0001"),
        effective_from_utc_ms=0,
        effective_to_utc_ms=TARGET + 1,
        source_kind="BASELINE",
        source_manifest_hash=SHA,
        verification_mode="APPROXIMATED",
        stress_multiplier=Decimal("1"),
        watermark="BASELINE_ASSUMPTION_NOT_VERIFIED",
        evidence_time_utc_ms=TARGET,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


def account(*, equity=Decimal("10000")):
    evidence = account_evidence_records(
        wallet=wallet_ledger_evidence(
            wallet_balance=equity,
            locked_initial_margin=Decimal("0"),
            locked_fee_reserve=Decimal("0"),
            locked_funding_reserve=Decimal("0"),
        ),
        valuations=(),
        positions=(),
        open_risks=(),
        pending_plans=(),
        experiment_state=experiment_state_evidence(event_time_utc_ms=TARGET, state="RUNNING"),
    )
    bundle = account_evidence_bundle(
        evidence,
        event_time_utc_ms=TARGET,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    return make_account_planning_snapshot(bundle, evidence, eligible_time_utc_ms=TARGET)


def inputs(
    *,
    side=Side.LONG,
    open_price=Decimal("100"),
    decision_close=Decimal("100"),
    atr=Decimal("10"),
    rule=None,
    equity=Decimal("10000"),
):
    intent_id = "eint_" + "1" * 24
    return SizingInputs(
        intent_id=intent_id,
        symbol="BTCUSDT",
        side=side,
        decision_close=decision_close,
        reference_price=open_price,
        atr=atr,
        contract=rule or contract(),
        cost=cost(),
        funding_risk=funding(),
        funding_event_upper_bound=3,
        account=account(equity=equity),
        subject=entry_intent_subject_ref_from_identity(
            entry_intent_id=intent_id,
            candidate_id="cand_" + "1" * 24,
            symbol="BTCUSDT",
            intent_content_hash="9" * 64,
        ),
        stage=ResearchStage.BACKTEST,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )


@registered("UT-SCHEMA-007", "2B-SCHEMA-007")
def test_sizing_success_is_distinct_from_rejection() -> None:
    assert position_sizing(inputs()).result_id.startswith("size_")
    result = position_sizing(inputs(rule=contract(min_qty=Decimal("999"))))
    assert result.reason is ExecutionRejectionReason.BELOW_MIN_QTY
    assert (
        position_sizing(replace(inputs(), cost=None)).reason
        is ExecutionRejectionReason.COST_MODEL_UNAVAILABLE
    )


@registered("UT-SCHEMA-012", "2B-SCHEMA-012")
def test_sizing_result_has_complete_cash_and_risk_inputs() -> None:
    names = {field.name for field in fields(type(position_sizing(inputs())))}
    assert {"unit_risk", "unscaled_required_cash", "funding_event_upper_bound"} <= names
    assert "input_hash" not in names


@registered("UT-SCHEMA-013", "2B-SCHEMA-013")
def test_minimum_failure_does_not_construct_nullable_result() -> None:
    result = position_sizing(inputs(rule=contract(min_notional=Decimal("999999"))))
    assert result.reason is ExecutionRejectionReason.BELOW_MIN_NOTIONAL


@registered("UT-GAP-001", "2B-GAP-001")
def test_long_adverse_gap_direction_and_threshold() -> None:
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("105"), Decimal("10")) == Decimal("5")
    with pytest.raises(SizingRejected, match="GAP_TOO_LARGE"):
        adverse_gap(Side.LONG, Decimal("100"), Decimal("105.1"), Decimal("10"))
    rejection = position_sizing(inputs(decision_close=Decimal("100"), open_price=Decimal("105.1")))
    assert rejection.reason is ExecutionRejectionReason.GAP_TOO_LARGE


@registered("UT-GAP-002", "2B-GAP-002")
def test_short_adverse_gap_direction_and_threshold() -> None:
    assert adverse_gap(Side.SHORT, Decimal("100"), Decimal("95"), Decimal("10")) == Decimal("5")
    with pytest.raises(SizingRejected, match="GAP_TOO_LARGE"):
        adverse_gap(Side.SHORT, Decimal("100"), Decimal("94.9"), Decimal("10"))


@registered("UT-GAP-003", "2B-GAP-003")
def test_gap_equal_to_half_atr_is_accepted() -> None:
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("105"), Decimal("10")) == Decimal("5")


@registered("UT-GAP-004", "2B-GAP-004")
def test_gap_is_independent_of_slippage_stress() -> None:
    assert adverse_gap(Side.LONG, Decimal("100"), Decimal("101"), Decimal("10")) == Decimal("1")
    assert (
        cost(stress=Decimal("1")).effective_slippage_rate
        != cost(stress=Decimal("2")).effective_slippage_rate
    )


@registered("UT-COST-001", "2B-COST-001")
def test_entry_slippage_is_applied_once_in_side_direction() -> None:
    long = price_geometry(Side.LONG, Decimal("100"), Decimal("10"), cost(), contract())
    short = price_geometry(Side.SHORT, Decimal("100"), Decimal("10"), cost(), contract())
    assert long.expected_entry_fill_price == Decimal("100.1")
    assert short.expected_entry_fill_price == Decimal("99.9")


@registered("UT-COST-002", "2B-COST-002")
def test_tick_rounding_matches_independent_directional_reference() -> None:
    for side in (Side.LONG, Side.SHORT):
        actual = price_geometry(side, Decimal("100.03"), Decimal("10.07"), cost(), contract())
        expected = reference_prices(
            side.value, Decimal("100.03"), Decimal("10.07"), Decimal("0.0001"), Decimal("0.1")
        )
        assert actual.as_price_tuple() == expected


@registered("UT-COST-003", "2B-COST-003")
def test_expected_exit_prices_do_not_double_apply_slippage() -> None:
    actual = price_geometry(Side.LONG, Decimal("100"), Decimal("10"), cost(), contract())
    expected = reference_prices(
        "LONG", Decimal("100"), Decimal("10"), Decimal("0.0001"), Decimal("0.1")
    )
    assert actual.expected_stop_fill_price == expected[3]
    assert actual.expected_take_profit_fill_price == expected[4]


@registered("UT-COST-005", "2B-COST-005")
def test_price_geometry_is_strict_after_tick_rounding() -> None:
    with pytest.raises(PriceGeometryInvalid):
        price_geometry(Side.LONG, Decimal("1"), Decimal("0.01"), cost(), contract())


@registered("UT-RISK-001", "2B-RISK-001")
def test_unit_risk_uses_stop_fee_and_funding_envelope() -> None:
    result = position_sizing(inputs())
    geometry = price_geometry(Side.LONG, Decimal("100"), Decimal("10"), cost(), contract())
    expected = reference_sizing(
        equity=Decimal("10000"),
        entry=geometry.expected_entry_fill_price,
        stop_fill=geometry.expected_stop_fill_price,
        exit_basis=geometry.planned_exit_notional_price_basis,
        fee_rate=Decimal("0.0005"),
        funding_rate=Decimal("0.0001"),
        funding_count=3,
        step=Decimal("0.001"),
    )
    assert result.unit_risk == expected[0]


@registered("UT-RISK-002", "2B-RISK-002")
def test_single_trade_budget_is_exactly_half_percent_equity() -> None:
    assert position_sizing(inputs()).single_risk_budget == Decimal("50.000")


@registered("UT-RISK-003", "2B-RISK-003")
def test_raw_quantity_is_budget_divided_by_unit_risk_without_prerounding() -> None:
    result = position_sizing(inputs())
    assert result.raw_quantity == result.single_risk_budget / result.unit_risk


@registered("UT-RISK-004", "2B-RISK-004")
def test_step_quantity_recomputed_risk_never_exceeds_budget() -> None:
    result = position_sizing(inputs())
    assert result.step_quantized_quantity * result.unit_risk <= result.single_risk_budget


@registered("UT-RISK-009", "2B-RISK-009")
def test_mutating_success_result_to_exceed_budget_fails_closed() -> None:
    result = position_sizing(inputs())
    with pytest.raises(ValueError):
        replace(result, step_quantized_quantity=result.raw_quantity + Decimal("1"))


@registered("UT-QTY-001", "2B-QTY-001")
def test_quantity_uses_floor_to_step() -> None:
    result = position_sizing(inputs())
    expected = reference_sizing(
        equity=Decimal("10000"),
        entry=result.expected_entry_fill_price,
        stop_fill=result.expected_stop_fill_price,
        exit_basis=result.planned_exit_notional_price_basis,
        fee_rate=Decimal("0.0005"),
        funding_rate=Decimal("0.0001"),
        funding_count=3,
        step=Decimal("0.001"),
    )[3]
    assert result.step_quantized_quantity == expected


@registered("UT-QTY-002", "2B-QTY-002")
def test_quantity_zero_has_distinct_high_priority_reason() -> None:
    result = position_sizing(inputs(rule=contract(min_qty=Decimal("0")), equity=Decimal("0.001")))
    assert result.reason is ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO


@registered("UT-QTY-003", "2B-QTY-003")
def test_minimum_quantity_equality_is_accepted() -> None:
    baseline = position_sizing(inputs())
    assert position_sizing(
        inputs(rule=contract(min_qty=baseline.step_quantized_quantity))
    ).result_id


@registered("UT-QTY-004", "2B-QTY-004")
def test_minimum_notional_uses_final_entry_fill_and_accepts_equality() -> None:
    baseline = position_sizing(inputs())
    minimum = baseline.step_quantized_quantity * baseline.expected_entry_fill_price
    assert position_sizing(inputs(rule=contract(min_notional=minimum))).result_id
