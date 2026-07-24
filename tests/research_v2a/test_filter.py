from dataclasses import asdict
from decimal import Decimal

from pa_agent.research_backtest.domain.enums import MarketView
from pa_agent.research_v2a.breakout_quality import (
    CANDIDATE_FILTER_VERSION,
    CandidateFilterOutcome,
    filter_candidate,
)
from tests.research_v2a.helpers import make_candidate


def test_filter_accepts_strength_equal_to_threshold_without_mutating_candidate() -> None:
    candidate = make_candidate(
        decision_time_utc_ms=1_700_000_000_000,
        strength="2",
    )
    before = asdict(candidate)

    decision = filter_candidate(
        candidate,
        threshold=Decimal("2"),
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
    )

    assert decision.outcome is CandidateFilterOutcome.ACCEPT
    assert decision.candidate is candidate
    assert asdict(candidate) == before
    assert decision.breakout_strength == Decimal("2")


def test_filter_rejects_only_as_weak_breakout() -> None:
    candidate = make_candidate(
        decision_time_utc_ms=1_700_000_000_000,
        strength="1.999",
        market_view=MarketView.SHORT,
    )

    decision = filter_candidate(
        candidate,
        threshold=Decimal("2"),
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
    )

    assert decision.outcome is CandidateFilterOutcome.REJECT_WEAK_BREAKOUT
    assert decision.candidate.candidate_id == candidate.candidate_id


def test_same_input_produces_identical_filter_canonical_bytes() -> None:
    candidate = make_candidate(
        decision_time_utc_ms=1_700_000_000_000,
        strength="3",
    )
    first = filter_candidate(
        candidate,
        threshold=Decimal("2"),
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
    )
    second = filter_candidate(
        candidate,
        threshold=Decimal("2"),
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
    )

    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
