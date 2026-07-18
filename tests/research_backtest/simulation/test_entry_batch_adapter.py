from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from pa_agent.research_backtest.domain.enums import MarketView
from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs


def _batch_inputs(
    *,
    existing_open_risk: Decimal = Decimal("0"),
    eth_min_qty=None,
    eth_decision_close: Decimal | None = Decimal("20"),
    eth_atr14: Decimal = Decimal("1"),
):
    from pa_agent.research_backtest.simulation.planning import (
        EntryBatchItemEvidence,
        EntryBatchPlanningInputs,
    )

    common = {"existing_open_risk": existing_open_risk}
    btc = complete_entry_inputs(**common)
    eth = complete_entry_inputs(
        **common,
        symbol="ETHUSDT",
        market_view=MarketView.SHORT,
        min_qty=eth_min_qty or Decimal("0.001"),
        decision_close_override=eth_decision_close,
        atr14_4h=eth_atr14,
    )

    def item(value):
        return EntryBatchItemEvidence(
            candidate=value.candidate,
            intent=value.intent,
            target_open=value.target_open,
            watermark=value.watermark,
            contract=value.contract,
            cost=value.cost,
            funding_schedule=value.funding_schedule,
            funding_risk=value.funding_risk,
            funding_event_upper_bound=value.sizing.funding_event_upper_bound,
        )

    return EntryBatchPlanningInputs(
        items=(item(btc), item(eth)),
        account=btc.account,
        account_evidence_bundle=btc.account_evidence_bundle,
        account_evidence_records=btc.account_evidence_records,
        open_risk_evidence_records=btc.open_risk_evidence_records,
        stage=btc.stage,
        split_start_utc_ms=btc.split_start_utc_ms,
        split_end_utc_ms=btc.split_end_utc_ms,
        code_commit=btc.code_commit,
        dependency_lock_hash=btc.dependency_lock_hash,
    )


def test_real_2b_batch_adapter_builds_one_shared_replayable_chain() -> None:
    from pa_agent.research_backtest.domain.base import verify_formal_identity
    from pa_agent.research_backtest.domain.canonical import canonical_dumps
    from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )

    inputs = _batch_inputs()
    outcome = build_entry_batch_planning_outcome(inputs)

    independently_rebuilt = tuple(build_entry_execution_plan(item) for item in outcome.plan_inputs)
    emitted = (*outcome.plans, *outcome.execution_rejections)
    assert tuple(plan.symbol for plan in outcome.plans) == ("BTCUSDT", "ETHUSDT")
    assert {canonical_dumps(item) for item in independently_rebuilt} <= {
        canonical_dumps(item) for item in emitted
    }
    assert len({item.account.snapshot_id for item in outcome.plan_inputs}) == 1
    assert len({item.batch.batch_id for item in outcome.plan_inputs}) == 1
    assert len({item.scaling.result_id for item in outcome.plan_inputs}) == 1
    accepted = tuple(
        item for item in outcome.scaling.item_results if hasattr(item, "final_planned_risk")
    )
    assert {item.symbol for item in accepted} == {"BTCUSDT", "ETHUSDT"}
    assert sum((item.final_planned_risk for item in accepted), Decimal("0")) <= Decimal("100")
    assert sum((item.final_required_cash for item in accepted), Decimal("0")) <= Decimal("10000")
    for value, id_field, hash_field, prefix in (
        *((item, "result_id", "result_content_hash", "size_") for item in outcome.sizing_results),
        (outcome.completeness, "completeness_id", "completeness_content_hash", "bcomplete_"),
        (outcome.batch, "batch_id", "batch_content_hash", "pbatch_"),
        (outcome.scaling, "result_id", "result_content_hash", "scale_"),
        *((item, "item_id", "item_content_hash", "asitem_") for item in accepted),
        *((plan, "plan_id", "plan_content_hash", "eplan_") for plan in outcome.plans),
    ):
        verify_formal_identity(value, id_field=id_field, hash_field=hash_field, prefix=prefix)


def test_real_2b_batch_adapter_is_order_invariant() -> None:
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )

    inputs = _batch_inputs()
    forward = build_entry_batch_planning_outcome(inputs)
    reverse = build_entry_batch_planning_outcome(
        replace(inputs, items=tuple(reversed(inputs.items)))
    )
    assert reverse.completeness == forward.completeness
    assert reverse.batch == forward.batch
    assert reverse.scaling == forward.scaling
    assert reverse.plans == forward.plans


def test_post_plan_cash_or_evidence_conflict_is_an_invariant_violation() -> None:
    import pytest

    from pa_agent.research_backtest.simulation.planning import (
        EntryBatchPostPlanInvariantError,
        build_entry_batch_planning_outcome,
        validate_entry_batch_post_plan,
    )

    outcome = build_entry_batch_planning_outcome(_batch_inputs())
    validate_entry_batch_post_plan(outcome, available_balance=Decimal("10000"))
    with pytest.raises(EntryBatchPostPlanInvariantError):
        validate_entry_batch_post_plan(outcome, available_balance=Decimal("9999"))
    original = outcome.plans[0]
    excessive_cash = SimpleNamespace(
        **{
            name: getattr(original, name)
            for name in (
                "plan_id",
                "symbol",
                "required_cash",
                "planned_risk",
                "portfolio_planning_batch_id",
                "portfolio_planning_batch_content_hash",
                "portfolio_scaling_result_id",
                "portfolio_scaling_result_content_hash",
                "accepted_scaling_item_id",
                "accepted_scaling_item_content_hash",
                "account_snapshot_id",
                "account_snapshot_hash",
            )
        }
    )
    excessive_cash.required_cash = Decimal("10001")
    with pytest.raises(EntryBatchPostPlanInvariantError):
        validate_entry_batch_post_plan(
            replace(outcome, plans=(excessive_cash,)),
            available_balance=Decimal("10000"),
        )
    wrong_batch = SimpleNamespace(**vars(excessive_cash))
    wrong_batch.required_cash = original.required_cash
    wrong_batch.portfolio_planning_batch_id = "pbatch_wrong"
    with pytest.raises(EntryBatchPostPlanInvariantError):
        validate_entry_batch_post_plan(
            replace(outcome, plans=(wrong_batch,)), available_balance=Decimal("10000")
        )
    with pytest.raises(EntryBatchPostPlanInvariantError):
        validate_entry_batch_post_plan(
            replace(outcome, plans=(original, original)),
            available_balance=Decimal("10000"),
        )


def test_rejected_quantized_item_does_not_rescale_accepted_peer() -> None:
    from pa_agent.research_backtest.domain.scaling import (
        AcceptedScalingItem,
        RejectedScalingItem,
    )
    from pa_agent.research_backtest.planning.prices import floor_to_step
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )

    outcome = build_entry_batch_planning_outcome(
        _batch_inputs(existing_open_risk=Decimal("40"), eth_min_qty=Decimal("20"))
    )
    accepted = tuple(
        item for item in outcome.scaling.item_results if isinstance(item, AcceptedScalingItem)
    )
    rejected = tuple(
        item for item in outcome.scaling.item_results if isinstance(item, RejectedScalingItem)
    )
    assert tuple(item.symbol for item in accepted) == ("BTCUSDT",)
    assert tuple(item.symbol for item in rejected) == ("ETHUSDT",)
    assert rejected[0] in outcome.audit_objects
    btc_sizing = next(item for item in outcome.sizing_results if item.symbol == "BTCUSDT")
    assert accepted[0].final_quantity == floor_to_step(
        btc_sizing.raw_quantity * outcome.scaling.final_scale,
        accepted[0].step_size,
    )
    assert outcome.scaling.final_scale < Decimal("1")
