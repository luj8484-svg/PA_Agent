from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.strategy.breakout_strength import (
    calculate_breakout_strength,
)

CANDIDATE_FILTER_VERSION = "BREAKOUT_QUALITY_FILTER_V2A_V1"
CANDIDATE_FILTER_DECISION_SCHEMA_VERSION = "V2A_CANDIDATE_FILTER_DECISION_V1"


class CandidateFilterOutcome(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT_WEAK_BREAKOUT = "REJECT_WEAK_BREAKOUT"


@dataclass(frozen=True, slots=True)
class CandidateFilterDecision:
    schema_version: str
    candidate: StrategyCandidate
    breakout_strength: Decimal
    threshold: Decimal
    outcome: CandidateFilterOutcome
    candidate_filter_version: str

    def canonical_json(self) -> str:
        return canonical_dumps(self)

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self)


def filter_candidate(
    candidate: StrategyCandidate,
    *,
    threshold: Decimal,
    candidate_filter_version: str,
) -> CandidateFilterDecision:
    if not isinstance(candidate, StrategyCandidate):
        raise TypeError("candidate must be a StrategyCandidate")
    if not isinstance(threshold, Decimal) or not threshold.is_finite() or threshold < 0:
        raise ValueError("threshold must be a finite nonnegative Decimal")
    if candidate_filter_version != CANDIDATE_FILTER_VERSION:
        raise ValueError("unsupported candidate filter version")
    strength = calculate_breakout_strength(
        market_view=candidate.market_view,
        decision_close=candidate.decision_close,
        prior_20_bar_donchian_upper=candidate.donchian_high_previous_20,
        prior_20_bar_donchian_lower=candidate.donchian_low_previous_20,
        decision_atr_4h=candidate.atr14_4h,
    )
    outcome = (
        CandidateFilterOutcome.ACCEPT
        if strength >= threshold
        else CandidateFilterOutcome.REJECT_WEAK_BREAKOUT
    )
    return CandidateFilterDecision(
        schema_version=CANDIDATE_FILTER_DECISION_SCHEMA_VERSION,
        candidate=candidate,
        breakout_strength=strength,
        threshold=threshold,
        outcome=outcome,
        candidate_filter_version=candidate_filter_version,
    )
