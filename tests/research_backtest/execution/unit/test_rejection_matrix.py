from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.candidates import strategy_candidate
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    MarketReason,
    MarketView,
    RejectionDisposition,
    ResearchStage,
    TrendState,
)
from pa_agent.research_backtest.domain.rejections import (
    candidate_subject_ref,
    entry_intent_subject_ref,
    portfolio_batch_subject_ref,
    rejection_fact,
)
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.planning.rejections import choose_rejection

SHA = "a" * 64
COMMIT = "b" * 40
DECISION = 14_400_000 - 1


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        function = pytest.mark.requirement_ids(requirement_id)(function)
        return pytest.mark.test_id(test_id)(function)

    return decorate


def candidate():
    return strategy_candidate(
        symbol="BTCUSDT",
        decision_time_utc_ms=DECISION,
        decision_bar_open_time_utc_ms=0,
        market_view=MarketView.LONG,
        market_reason=MarketReason.BULL_DONCHIAN_BREAKOUT,
        decision_close=Decimal("121"),
        daily_close=Decimal("110"),
        trend_state=TrendState.BULL,
        ema50_daily=Decimal("105"),
        ema200_daily=Decimal("100"),
        atr14_4h=Decimal("10"),
        donchian_high_previous_20=Decimal("120"),
        donchian_low_previous_20=Decimal("80"),
        decision_visible_input_hash=SHA,
        indicator_config_hash="c" * 64,
        strategy_config_hash="d" * 64,
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )


def intent():
    return make_entry_intent(
        candidate(),
        execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
        computational_experiment_id="f" * 64,
        stage=ResearchStage.BACKTEST,
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )


def reject(subject, reasons, stage=ResearchStage.BACKTEST):
    return choose_rejection(
        subject=subject,
        event_time_utc_ms=14_460_000,
        facts=tuple(rejection_fact(reason) for reason in reasons),
        stage=stage,
        relevant_version_hashes=(("config", SHA),),
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )


@registered("UT-SCHEMA-005", "2B-SCHEMA-005")
def test_rejection_subjects_are_distinct_closed_tagged_union_types() -> None:
    candidate_ref = candidate_subject_ref(candidate())
    intent_ref = entry_intent_subject_ref(intent())
    batch_ref = portfolio_batch_subject_ref(
        portfolio_planning_batch_id="pbatch_" + "1" * 24,
        symbols=("ETHUSDT", "BTCUSDT"),
        ordered_entry_intent_ids=("eint_" + "1" * 24, "eint_" + "2" * 24),
        batch_content_hash="1" * 64,
        account_snapshot_hash="2" * 64,
        target_open_snapshot_hashes=("3" * 64, "4" * 64),
    )
    assert type(candidate_ref).__name__ == "CandidateSubjectRef"
    assert type(intent_ref).__name__ == "EntryIntentSubjectRef"
    assert type(batch_ref).__name__ == "PortfolioBatchSubjectRef"
    assert "decision_visible_input_hash" not in {field.name for field in fields(type(batch_ref))}


@registered("PT-REJECTION-SUBJECT-CARDINALITY", "2B-SCHEMA-005")
def test_single_subjects_have_one_symbol_and_batch_subject_has_many() -> None:
    assert candidate_subject_ref(candidate()).symbols == ("BTCUSDT",)
    assert entry_intent_subject_ref(intent()).symbols == ("BTCUSDT",)
    batch_ref = portfolio_batch_subject_ref(
        portfolio_planning_batch_id="pbatch_" + "1" * 24,
        symbols=("ETHUSDT", "BTCUSDT"),
        ordered_entry_intent_ids=("eint_" + "1" * 24, "eint_" + "2" * 24),
        batch_content_hash="1" * 64,
        account_snapshot_hash="2" * 64,
        target_open_snapshot_hashes=("3" * 64, "4" * 64),
    )
    assert batch_ref.symbols == ("BTCUSDT", "ETHUSDT")


@registered("UT-PORT-005", "2B-PORT-005")
def test_portfolio_rejection_uses_the_formal_batch_subject() -> None:
    subject = portfolio_batch_subject_ref(
        portfolio_planning_batch_id="pbatch_" + "1" * 24,
        symbols=("BTCUSDT", "ETHUSDT"),
        ordered_entry_intent_ids=("eint_" + "1" * 24, "eint_" + "2" * 24),
        batch_content_hash="1" * 64,
        account_snapshot_hash="2" * 64,
        target_open_snapshot_hashes=("3" * 64, "4" * 64),
    )
    result = reject(subject, (ExecutionRejectionReason.TOTAL_RISK_ALREADY_AT_LIMIT,))
    assert result.subject is subject
    assert result.disposition is RejectionDisposition.CANDIDATE_REJECTED
    assert result.retry_allowed is True
    illegal_pre_batch_reason = reject(subject, (ExecutionRejectionReason.BATCH_INCOMPLETE,))
    assert illegal_pre_batch_reason.reason is ExecutionRejectionReason.DATA_INVALID


@registered("PT-BATCH-SUBJECT-STABLE", "2B-PORT-005")
def test_batch_subject_identity_is_stable_under_symbol_input_permutation() -> None:
    common = {
        "portfolio_planning_batch_id": "pbatch_" + "1" * 24,
        "ordered_entry_intent_ids": ("eint_" + "1" * 24, "eint_" + "2" * 24),
        "batch_content_hash": "1" * 64,
        "account_snapshot_hash": "2" * 64,
        "target_open_snapshot_hashes": ("3" * 64, "4" * 64),
    }
    left = portfolio_batch_subject_ref(symbols=("BTCUSDT", "ETHUSDT"), **common)
    right = portfolio_batch_subject_ref(symbols=("ETHUSDT", "BTCUSDT"), **common)
    assert left == right


@registered("UT-ID-005", "2B-ID-005")
def test_rejection_priority_is_independent_of_validator_order() -> None:
    subject = entry_intent_subject_ref(intent())
    reasons = (
        ExecutionRejectionReason.BELOW_MIN_NOTIONAL,
        ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
        ExecutionRejectionReason.DATA_INVALID,
    )
    assert reject(subject, reasons).reason is ExecutionRejectionReason.DATA_INVALID
    assert (
        reject(subject, tuple(reversed(reasons))).rejection_id
        == reject(subject, reasons).rejection_id
    )


@registered("PT-PRIORITY-ORDER", "2B-ID-005")
def test_disposition_depends_on_subject_reason_and_research_stage() -> None:
    subject = entry_intent_subject_ref(intent())
    reason = (ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,)
    backtest = reject(subject, reason, ResearchStage.BACKTEST)
    paper = reject(subject, reason, ResearchStage.PAPER_SIMULATION)
    live = reject(subject, reason, ResearchStage.LIVE_ELIGIBILITY_RESEARCH)
    assert (backtest.disposition, backtest.retry_allowed) == (
        RejectionDisposition.EXECUTION_PATH_INVALID,
        False,
    )
    assert (paper.disposition, paper.retry_allowed) == (
        RejectionDisposition.EXECUTION_PATH_INVALID,
        True,
    )
    assert (live.disposition, live.retry_allowed) == (
        RejectionDisposition.EXPERIMENT_INVALID,
        False,
    )
    illegal = reject(candidate_subject_ref(candidate()), (ExecutionRejectionReason.GAP_TOO_LARGE,))
    assert illegal.reason is ExecutionRejectionReason.DATA_INVALID
