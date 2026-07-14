from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState
from pa_agent.research_backtest.versions import (
    DECISION_VISIBLE_INPUT_VERSION,
    STRATEGY_CANDIDATE_SCHEMA_VERSION,
    STRATEGY_ID,
    STRATEGY_VERSION,
)


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    schema_version: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    decision_time_utc_ms: int
    decision_bar_open_time_utc_ms: int
    market_view: MarketView
    market_reason: MarketReason
    decision_close: Decimal
    daily_close: Decimal
    trend_state: TrendState
    ema50_daily: Decimal
    ema200_daily: Decimal
    atr14_4h: Decimal
    donchian_high_previous_20: Decimal
    donchian_low_previous_20: Decimal
    decision_visible_input_hash: str
    decision_visible_input_version: str
    indicator_config_hash: str
    strategy_config_hash: str
    code_commit: str
    dependency_lock_hash: str
    created_by: str

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def candidate_id_for(candidate: StrategyCandidate) -> str:
    payload = asdict(candidate)
    payload.pop("candidate_id")
    return f"cand_{canonical_sha256(payload)[:24]}"


def strategy_candidate(**values: object) -> StrategyCandidate:
    candidate = StrategyCandidate(
        schema_version=STRATEGY_CANDIDATE_SCHEMA_VERSION,
        candidate_id="",
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        decision_visible_input_version=DECISION_VISIBLE_INPUT_VERSION,
        created_by="PYTHON_DETERMINISTIC",
        **values,
    )
    return replace(candidate, candidate_id=candidate_id_for(candidate))

