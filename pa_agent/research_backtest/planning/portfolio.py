from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import AccountPlanningSnapshot
from pa_agent.research_backtest.domain.batches import (
    ExpectedIntentRef,
    PortfolioBatchCompletenessSnapshot,
    PortfolioPlanningBatch,
    ResolutionRef,
    portfolio_batch_completeness_snapshot,
)
from pa_agent.research_backtest.domain.contracts import ContractRuleCoverage
from pa_agent.research_backtest.domain.costs import CostModelSnapshot
from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason, ResearchStage
from pa_agent.research_backtest.domain.market_inputs import TargetMinuteOpenSnapshot
from pa_agent.research_backtest.domain.rejections import (
    EntryIntentSubjectRef,
    ExecutionRejection,
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
from pa_agent.research_backtest.domain.sizing import PositionSizingResult
from pa_agent.research_backtest.planning.cash import calculate_final_required_cash
from pa_agent.research_backtest.planning.prices import floor_to_step
from pa_agent.research_backtest.planning.rejections import choose_rejection
from pa_agent.research_backtest.versions import (
    ACCEPTED_SCALING_ITEM_SCHEMA_VERSION,
    PORTFOLIO_SCALING_MODEL_VERSION,
    PORTFOLIO_SCALING_RESULT_SCHEMA_VERSION,
    REJECTED_SCALING_ITEM_SCHEMA_VERSION,
)


def resolve_batch_completeness(
    expected_intents: tuple[ExpectedIntentRef, ...],
    resolutions: tuple[ResolutionRef, ...],
    *,
    subject: EntryIntentSubjectRef,
    completeness_event_time_utc_ms: int,
    source_event_id: str,
    stage: ResearchStage,
    code_commit: str,
    dependency_lock_hash: str,
) -> PortfolioBatchCompletenessSnapshot | ExecutionRejection:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
    expected_ids = tuple(sorted(item.entry_intent_id for item in expected_intents))
    resolution_ids = tuple(sorted(item.entry_intent_id for item in resolutions))
    missing_only = len(resolution_ids) == len(set(resolution_ids)) and set(resolution_ids) < set(
        expected_ids
    )
    if resolution_ids != expected_ids:
        reason = (
            ExecutionRejectionReason.BATCH_INCOMPLETE
            if missing_only
            else ExecutionRejectionReason.DATA_INVALID
        )
        return choose_rejection(
            subject=subject,
            event_time_utc_ms=completeness_event_time_utc_ms,
            facts=(rejection_fact(reason),),
            stage=stage,
            relevant_version_hashes=(("entry_intent_subject", subject.subject_content_hash),),
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    try:
        return portfolio_batch_completeness_snapshot(
            expected_intents,
            resolutions,
            completeness_event_time_utc_ms=completeness_event_time_utc_ms,
            source_event_id=source_event_id,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
    except ValueError:
        return choose_rejection(
            subject=subject,
            event_time_utc_ms=completeness_event_time_utc_ms,
            facts=(rejection_fact(ExecutionRejectionReason.DATA_INVALID),),
            stage=stage,
            relevant_version_hashes=(("entry_intent_subject", subject.subject_content_hash),),
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )


def scale_portfolio(
    batch: PortfolioPlanningBatch,
    account: AccountPlanningSnapshot,
    sizing_results: tuple[PositionSizingResult, ...],
    contracts: dict[str, ContractRuleCoverage],
    costs: dict[str, CostModelSnapshot],
    target_open_snapshots: tuple[TargetMinuteOpenSnapshot, ...],
    stage: ResearchStage,
    *,
    rejection_audit: list[ExecutionRejection] | None = None,
) -> PortfolioScalingResult | ExecutionRejection:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    assert_deterministic_research_runtime()
    if not isinstance(stage, ResearchStage):
        raise ValueError("invalid research stage")
    ordered = tuple(sorted(sizing_results, key=lambda item: (item.symbol, item.result_id)))
    if tuple(item.result_id for item in ordered) != batch.ordered_successful_sizing_result_ids:
        raise ValueError("sizing inputs do not equal batch successful projection")
    ordered_opens = tuple(sorted(target_open_snapshots, key=lambda item: item.symbol))
    if (
        len(ordered_opens) != len(batch.target_open_snapshot_ids)
        or tuple(item.snapshot_id for item in ordered_opens) != batch.target_open_snapshot_ids
        or tuple(item.symbol for item in ordered_opens) != tuple(item.symbol for item in ordered)
        or any(item.open_time_utc_ms != batch.eligible_time_utc_ms for item in ordered_opens)
        or any(
            snapshot.open_price != sizing.reference_price
            for snapshot, sizing in zip(ordered_opens, ordered, strict=True)
        )
    ):
        raise ValueError("target-open evidence does not match batch rows")
    target_open_snapshot_hashes = tuple(item.snapshot_content_hash for item in ordered_opens)
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
    subject = portfolio_batch_subject_ref(
        portfolio_planning_batch_id=batch.batch_id,
        symbols=batch.ordered_symbols,
        ordered_entry_intent_ids=batch.ordered_entry_intent_ids,
        batch_content_hash=batch.batch_content_hash,
        account_snapshot_hash=batch.account_snapshot_hash,
        target_open_snapshot_hashes=target_open_snapshot_hashes,
    )

    def reject(reason: ExecutionRejectionReason) -> ExecutionRejection:
        return choose_rejection(
            subject=subject,
            event_time_utc_ms=batch.eligible_time_utc_ms,
            facts=(rejection_fact(reason),),
            stage=stage,
            relevant_version_hashes=(("batch", batch.batch_content_hash),),
            code_commit=batch.code_commit,
            dependency_lock_hash=batch.dependency_lock_hash,
        )

    if base_risk >= risk_limit:
        return reject(ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT)
    remaining = risk_limit - base_risk
    if account.pending_plan_reserve > account.available_balance:
        raise ValueError("pending reserve exceeds available balance")
    deployable = account.available_balance - account.pending_plan_reserve
    sum_risk = sum((item.unscaled_planned_risk for item in ordered), Decimal("0"))
    sum_cash = sum((item.unscaled_required_cash for item in ordered), Decimal("0"))
    if deployable == 0 and sum_cash > 0:
        return reject(ExecutionRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE)
    risk_scale = Decimal("1") if sum_risk == 0 else remaining / sum_risk
    cash_scale = Decimal("1") if sum_cash == 0 else deployable / sum_cash
    final_scale = min(Decimal("1"), risk_scale, cash_scale)
    items = []
    for sizing in ordered:
        contract = contracts.get(sizing.result_id)
        if contract is None or contract.coverage_id != sizing.contract_rule_coverage_id:
            raise ValueError("contract evidence does not match sizing result")
        cost = costs.get(sizing.result_id)
        if cost is None or cost.snapshot_id != sizing.cost_model_snapshot_id:
            raise ValueError("cost evidence does not match sizing result")
        quantity = floor_to_step(sizing.raw_quantity * final_scale, contract.step_size)
        if quantity == 0:
            reason = ExecutionRejectionReason.QUANTITY_ROUNDED_TO_ZERO
        elif quantity < contract.min_qty:
            reason = ExecutionRejectionReason.BELOW_MIN_QTY
        elif quantity * sizing.expected_entry_fill_price < contract.min_notional:
            reason = ExecutionRejectionReason.BELOW_MIN_NOTIONAL
        else:
            payload = {
                "schema_version": ACCEPTED_SCALING_ITEM_SCHEMA_VERSION,
                "symbol": sizing.symbol,
                "sizing_result_id": sizing.result_id,
                "final_quantity": quantity,
                "final_notional": quantity * sizing.expected_entry_fill_price,
                "final_planned_risk": quantity * sizing.unit_risk,
                "final_required_cash": calculate_final_required_cash(
                    quantity=quantity,
                    expected_entry_fill_price=sizing.expected_entry_fill_price,
                    planned_exit_notional_price_basis=sizing.planned_exit_notional_price_basis,
                    effective_fee_rate=cost.effective_fee_rate,
                    effective_adverse_rate_cap=sizing.effective_adverse_rate_cap,
                    funding_event_upper_bound=sizing.funding_event_upper_bound,
                ),
                "step_size": contract.step_size,
                "minimum_status": "PASSED_MIN_QTY_AND_NOTIONAL",
            }
            items.append(accepted_scaling_item(payload))
            continue
        rejection = choose_rejection(
            subject=subject,
            event_time_utc_ms=batch.eligible_time_utc_ms,
            facts=(rejection_fact(reason),),
            stage=stage,
            relevant_version_hashes=(("batch", batch.batch_content_hash),),
            code_commit=batch.code_commit,
            dependency_lock_hash=batch.dependency_lock_hash,
        )
        if rejection_audit is not None:
            rejection_audit.append(rejection)
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
