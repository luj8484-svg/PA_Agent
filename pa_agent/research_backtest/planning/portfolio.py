from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import AccountPlanningSnapshot
from pa_agent.research_backtest.domain.batches import PortfolioPlanningBatch
from pa_agent.research_backtest.domain.contracts import ContractRuleCoverage
from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, ResearchStage
from pa_agent.research_backtest.domain.rejections import (
    portfolio_batch_subject_ref,
    rejection_fact,
)
from pa_agent.research_backtest.domain.scaling import (
    AcceptedScalingItem,
    PortfolioScalingResult,
    accepted_scaling_item,
    portfolio_scaling_result,
    rejected_scaling_item,
)
from pa_agent.research_backtest.domain.sizing import PositionSizingResult, SizingRejected
from pa_agent.research_backtest.planning.prices import floor_to_step
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.versions import (
    ACCEPTED_SCALING_ITEM_SCHEMA_VERSION,
    PORTFOLIO_SCALING_MODEL_VERSION,
    PORTFOLIO_SCALING_RESULT_SCHEMA_VERSION,
    REJECTED_SCALING_ITEM_SCHEMA_VERSION,
)


def scale_portfolio(
    batch: PortfolioPlanningBatch,
    account: AccountPlanningSnapshot,
    sizing_results: tuple[PositionSizingResult, ...],
    contracts: dict[str, ContractRuleCoverage],
) -> PortfolioScalingResult:
    ordered = tuple(sorted(sizing_results, key=lambda item: (item.symbol, item.result_id)))
    if tuple(item.result_id for item in ordered) != batch.ordered_successful_sizing_result_ids:
        raise ValueError("sizing inputs do not equal batch successful projection")
    if (
        account.snapshot_id != batch.account_snapshot_id
        or account.snapshot_hash != batch.account_snapshot_hash
    ):
        raise ValueError("account snapshot does not match planning batch")
    if any(
        item.account_snapshot_id != account.snapshot_id
        or item.account_snapshot_hash != account.snapshot_hash
        for item in ordered
    ):
        raise ValueError("sizing result account evidence does not match batch")
    base_risk = account.existing_open_risk + account.pending_plan_risk
    risk_limit = account.current_equity * Decimal("0.01")
    if base_risk >= risk_limit:
        raise SizingRejected("TOTAL_RISK_ALREADY_AT_LIMIT")
    remaining = risk_limit - base_risk
    if account.pending_plan_reserve > account.available_balance:
        raise ValueError("pending reserve exceeds available balance")
    deployable = account.available_balance - account.pending_plan_reserve
    sum_risk = sum((item.unscaled_planned_risk for item in ordered), Decimal("0"))
    sum_cash = sum((item.unscaled_required_cash for item in ordered), Decimal("0"))
    if deployable == 0 and sum_cash > 0:
        raise SizingRejected("INSUFFICIENT_AVAILABLE_BALANCE")
    risk_scale = Decimal("1") if sum_risk == 0 else remaining / sum_risk
    cash_scale = Decimal("1") if sum_cash == 0 else deployable / sum_cash
    final_scale = min(Decimal("1"), risk_scale, cash_scale)
    subject = portfolio_batch_subject_ref(
        portfolio_planning_batch_id=batch.batch_id,
        symbols=batch.ordered_symbols,
        ordered_entry_intent_ids=batch.ordered_entry_intent_ids,
        batch_content_hash=batch.batch_content_hash,
        account_snapshot_hash=batch.account_snapshot_hash,
        target_open_snapshot_hashes=tuple("0" * 64 for _ in batch.ordered_symbols),
    )
    items = []
    for sizing in ordered:
        contract = contracts.get(sizing.result_id)
        if contract is None or contract.coverage_id != sizing.contract_rule_coverage_id:
            raise ValueError("contract evidence does not match sizing result")
        quantity = floor_to_step(sizing.raw_quantity * final_scale, contract.step_size)
        if quantity == 0:
            reason = ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO
        elif quantity < contract.min_qty:
            reason = ExecutionRejectionReason.BELOW_MIN_QTY
        elif quantity * sizing.expected_entry_fill_price < contract.min_notional:
            reason = ExecutionRejectionReason.BELOW_MIN_NOTIONAL
        else:
            per_unit_cash = sizing.unscaled_required_cash / sizing.raw_quantity
            payload = {
                "schema_version": ACCEPTED_SCALING_ITEM_SCHEMA_VERSION,
                "symbol": sizing.symbol,
                "sizing_result_id": sizing.result_id,
                "final_quantity": quantity,
                "final_notional": quantity * sizing.expected_entry_fill_price,
                "final_planned_risk": quantity * sizing.unit_risk,
                "final_required_cash": quantity * per_unit_cash,
                "step_size": contract.step_size,
                "minimum_status": "PASSED_MIN_QTY_AND_NOTIONAL",
            }
            items.append(accepted_scaling_item(payload))
            continue
        rejection = choose_rejection(
            subject=subject,
            event_time_utc_ms=batch.eligible_time_utc_ms,
            facts=(rejection_fact(reason),),
            stage=ResearchStage.BACKTEST,
            relevant_version_hashes=(("batch", batch.batch_content_hash),),
            code_commit=batch.code_commit,
            dependency_lock_hash=batch.dependency_lock_hash,
        )
        items.append(
            rejected_scaling_item(
                {
                    "schema_version": REJECTED_SCALING_ITEM_SCHEMA_VERSION,
                    "symbol": sizing.symbol,
                    "sizing_result_id": sizing.result_id,
                    "rejection_id": rejection.rejection_id,
                }
            )
        )
    ordered_items = tuple(
        sorted(items, key=lambda item: (item.symbol, item.sizing_result_id, item.item_id))
    )
    accepted_risk = sum(
        (
            item.final_planned_risk
            for item in ordered_items
            if isinstance(item, AcceptedScalingItem)
        ),
        Decimal("0"),
    )
    if base_risk + accepted_risk > risk_limit:
        raise ValueError("scaled portfolio exceeds total risk limit")
    payload = {
        "schema_version": PORTFOLIO_SCALING_RESULT_SCHEMA_VERSION,
        "portfolio_planning_batch_id": batch.batch_id,
        "portfolio_planning_batch_content_hash": batch.batch_content_hash,
        "eligible_time_utc_ms": batch.eligible_time_utc_ms,
        "account_snapshot_id": account.snapshot_id,
        "account_snapshot_hash": account.snapshot_hash,
        "ordered_input_result_ids": batch.ordered_successful_sizing_result_ids,
        "remaining_risk": remaining,
        "deployable_cash": deployable,
        "risk_scale": risk_scale,
        "cash_scale": cash_scale,
        "final_scale": final_scale,
        "item_results": ordered_items,
        "scaling_model_version": PORTFOLIO_SCALING_MODEL_VERSION,
    }
    return portfolio_scaling_result(payload)
