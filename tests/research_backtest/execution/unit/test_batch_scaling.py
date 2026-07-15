from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.accounts import (
    account_evidence_bundle,
    account_evidence_records,
    experiment_state_evidence,
    make_account_planning_snapshot,
    wallet_ledger_evidence,
)
from pa_agent.research_backtest.domain.batches import (
    expected_intent_ref,
    portfolio_batch_completeness_snapshot,
    portfolio_planning_batch,
    resolution_ref,
)
from pa_agent.research_backtest.domain.contracts import verified_contract_rule
from pa_agent.research_backtest.domain.enums import ResolutionKind, Side
from pa_agent.research_backtest.domain.sizing import position_sizing_result
from pa_agent.research_backtest.planning.portfolio import scale_portfolio
from tests.research_backtest.execution.fixtures.reference_portfolio import reference_scale

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
TIME = 20_000_000


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        return pytest.mark.test_id(test_id)(pytest.mark.requirement_ids(requirement_id)(function))

    return decorate


def account(*, balance=Decimal("10000")):
    evidence = account_evidence_records(
        wallet=wallet_ledger_evidence(
            wallet_balance=balance,
            locked_initial_margin=Decimal("0"),
            locked_fee_reserve=Decimal("0"),
            locked_funding_reserve=Decimal("0"),
        ),
        valuations=(),
        positions=(),
        open_risks=(),
        pending_plans=(),
        experiment_state=experiment_state_evidence(event_time_utc_ms=TIME, state="RUNNING"),
    )
    bundle = account_evidence_bundle(
        evidence,
        event_time_utc_ms=TIME,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    return make_account_planning_snapshot(bundle, evidence, eligible_time_utc_ms=TIME)


def sizing(
    symbol: str,
    index: int,
    acct,
    contract,
    *,
    raw=Decimal("1"),
    risk=Decimal("50"),
    cash=Decimal("1000"),
):
    entry = Decimal("100") if symbol == "BTCUSDT" else Decimal("10")
    payload = {
        "schema_version": "POSITION_SIZING_RESULT_SCHEMA_V1",
        "intent_id": "eint_" + str(index) * 24,
        "symbol": symbol,
        "side": Side.LONG,
        "reference_price": entry,
        "expected_entry_fill_price": entry,
        "stop_trigger_price": entry - Decimal("2"),
        "take_profit_trigger_price": entry + Decimal("3"),
        "expected_stop_fill_price": entry - Decimal("2.1"),
        "expected_take_profit_fill_price": entry + Decimal("2.9"),
        "planned_exit_notional_price_basis": entry + Decimal("2.9"),
        "funding_notional_price_basis": entry + Decimal("2.9"),
        "unit_risk": risk / raw,
        "single_risk_budget": risk,
        "raw_quantity": raw,
        "step_quantized_quantity": raw,
        "unscaled_planned_risk": risk,
        "unscaled_required_cash": cash,
        "contract_rule_coverage_id": contract.coverage_id,
        "cost_model_snapshot_id": "cost_" + str(index) * 24,
        "funding_risk_config_id": "frisk_" + str(index) * 24,
        "funding_event_upper_bound": 1,
        "effective_adverse_rate_cap": Decimal("0.0001"),
        "account_snapshot_id": acct.snapshot_id,
        "account_snapshot_hash": acct.snapshot_hash,
        "sizing_model_version": "POSITION_SIZING_MODEL_V2",
    }
    return position_sizing_result(payload)


def rule(symbol: str, index: int, *, min_qty=Decimal("0")):
    return verified_contract_rule(
        symbol=symbol,
        query_time_utc_ms=TIME,
        source_kind="ARCHIVE",
        source_uri_or_archive_id=f"rule-{index}",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=TIME + 1,
        rule_version=f"RULE-{index}",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=min_qty,
        min_notional=Decimal("0"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash=SHA,
    )


def complete(*, reverse=False, eth_min=Decimal("0"), balance=Decimal("10000")):
    acct = account(balance=balance)
    btc_rule = rule("BTCUSDT", 1)
    eth_rule = rule("ETHUSDT", 2, min_qty=eth_min)
    btc = sizing("BTCUSDT", 1, acct, btc_rule)
    eth = sizing("ETHUSDT", 2, acct, eth_rule)
    expected = (
        expected_intent_ref(btc.intent_id, btc.symbol, TIME),
        expected_intent_ref(eth.intent_id, eth.symbol, TIME),
    )
    resolutions = tuple(
        resolution_ref(
            item.entry_intent_id,
            item.symbol,
            ResolutionKind.SIZING_RESULT,
            result.result_id,
            result.result_content_hash,
        )
        for item, result in zip(expected, (btc, eth), strict=True)
    )
    if reverse:
        expected, resolutions = tuple(reversed(expected)), tuple(reversed(resolutions))
    completeness = portfolio_batch_completeness_snapshot(
        expected,
        resolutions,
        completeness_event_time_utc_ms=TIME,
        source_event_id="complete-event-1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    batch = portfolio_planning_batch(
        completeness,
        acct,
        target_open_snapshot_ids=("tmopen_" + "1" * 24, "tmopen_" + "2" * 24),
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    rules = {btc.result_id: btc_rule, eth.result_id: eth_rule}
    return batch, acct, (btc, eth), rules


@registered("UT-SCHEMA-018", "2B-SCHEMA-018")
def test_completeness_is_a_formal_content_addressed_object() -> None:
    batch, _, _, _ = complete()
    assert batch.completeness_snapshot_id.startswith("bcomplete_")
    assert batch.ordered_entry_intent_ids


@registered("UT-PORT-008", "2B-PORT-008")
def test_each_expected_intent_requires_exactly_one_resolution() -> None:
    expected = (expected_intent_ref("eint_" + "1" * 24, "BTCUSDT", TIME),)
    with pytest.raises(ValueError, match="resolution"):
        portfolio_batch_completeness_snapshot(
            expected,
            (),
            completeness_event_time_utc_ms=TIME,
            source_event_id="complete-event",
            code_commit=COMMIT,
            dependency_lock_hash=LOCK,
        )


@registered("UT-TIME-014", "2B-TIME-014")
def test_completeness_event_cannot_precede_eligible_time() -> None:
    expected = (expected_intent_ref("eint_" + "1" * 24, "BTCUSDT", TIME),)
    row = resolution_ref(
        expected[0].entry_intent_id,
        "BTCUSDT",
        ResolutionKind.EXECUTION_PATH_INVALID,
        "rej_" + "1" * 24,
        SHA,
    )
    with pytest.raises(ValueError, match="event time"):
        portfolio_batch_completeness_snapshot(
            expected,
            (row,),
            completeness_event_time_utc_ms=TIME - 1,
            source_event_id="complete-event",
            code_commit=COMMIT,
            dependency_lock_hash=LOCK,
        )


@registered("UT-PORT-001", "2B-PORT-001")
def test_same_target_items_scale_together_after_complete_batch() -> None:
    batch, acct, results, rules = complete(balance=Decimal("1000"))
    scaled = scale_portfolio(batch, acct, results, rules)
    assert scaled.ordered_input_result_ids == batch.ordered_successful_sizing_result_ids
    assert len(scaled.item_results) == 2


@registered("UT-PORT-002", "2B-PORT-002")
def test_batch_and_scaling_are_order_invariant() -> None:
    left = complete(reverse=False)
    right = complete(reverse=True)
    assert left[0] == right[0]
    assert scale_portfolio(*left) == scale_portfolio(*right)


@registered("UT-PORT-003", "2B-PORT-003")
def test_final_scale_is_minimum_of_one_risk_and_cash() -> None:
    batch, acct, results, rules = complete(balance=Decimal("1000"))
    scaled = scale_portfolio(batch, acct, results, rules)
    expected = reference_scale(
        remaining_risk=acct.current_equity * Decimal("0.01"),
        deployable_cash=acct.available_balance,
        risks=tuple(item.unscaled_planned_risk for item in results),
        cash=tuple(item.unscaled_required_cash for item in results),
    )
    assert scaled.final_scale == expected


@registered("UT-PORT-004", "2B-PORT-004")
def test_rejected_scaled_item_does_not_redistribute_to_other_item() -> None:
    batch, acct, results, rules = complete(balance=Decimal("1000"), eth_min=Decimal("1"))
    scaled = scale_portfolio(batch, acct, results, rules)
    assert scaled.final_scale == Decimal("0.1")
    assert {type(item).__name__ for item in scaled.item_results} == {
        "AcceptedScalingItem",
        "RejectedScalingItem",
    }


@registered("UT-PORT-009", "2B-PORT-009")
def test_scaling_result_binds_exactly_one_batch() -> None:
    batch, acct, results, rules = complete()
    scaled = scale_portfolio(batch, acct, results, rules)
    assert scaled.portfolio_planning_batch_id == batch.batch_id
    assert scaled.portfolio_planning_batch_content_hash == batch.batch_content_hash


@registered("UT-SCHEMA-019", "2B-SCHEMA-019")
def test_accepted_item_has_no_opaque_input_hash() -> None:
    scaled = scale_portfolio(*complete())
    accepted = next(
        item for item in scaled.item_results if type(item).__name__ == "AcceptedScalingItem"
    )
    assert "item_input_hash" not in {field.name for field in fields(type(accepted))}
