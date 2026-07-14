from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
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

    def __post_init__(self) -> None:
        if self.schema_version != STRATEGY_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported StrategyCandidate schema version")
        if self.strategy_id != STRATEGY_ID or self.strategy_version != STRATEGY_VERSION:
            raise ValueError("unsupported strategy identity")
        if self.decision_visible_input_version != DECISION_VISIBLE_INPUT_VERSION:
            raise ValueError("unsupported decision-visible input version")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported candidate symbol")
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("candidate must be created by deterministic Python")
        if (
            type(self.decision_time_utc_ms) is not int
            or type(self.decision_bar_open_time_utc_ms) is not int
        ):
            raise ValueError("candidate times must be integer UTC milliseconds")
        if self.decision_bar_open_time_utc_ms >= self.decision_time_utc_ms:
            raise ValueError("decision bar open time must precede decision time")

        prices = (
            self.decision_close,
            self.daily_close,
            self.ema50_daily,
            self.ema200_daily,
            self.atr14_4h,
            self.donchian_high_previous_20,
            self.donchian_low_previous_20,
        )
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            for value in prices
        ):
            raise ValueError("candidate prices and indicators must be finite and positive")
        if self.donchian_high_previous_20 < self.donchian_low_previous_20:
            raise ValueError("Donchian high must be >= Donchian low")
        if not isinstance(self.market_view, MarketView) or not isinstance(
            self.market_reason, MarketReason
        ):
            raise ValueError("candidate market view and reason must use frozen enums")
        if not isinstance(self.trend_state, TrendState):
            raise ValueError("candidate trend state must use the frozen enum")

        expected_market = classify_market(
            trend_state=self.trend_state,
            current_close=self.decision_close,
            donchian_high=self.donchian_high_previous_20,
            donchian_low=self.donchian_low_previous_20,
        )
        if (
            self.market_view is not expected_market.market_view
            or self.market_reason is not expected_market.market_reason
        ):
            raise ValueError("candidate market fields contradict deterministic rules")

        sha256_fields = (
            self.decision_visible_input_hash,
            self.indicator_config_hash,
            self.strategy_config_hash,
            self.dependency_lock_hash,
        )
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in sha256_fields):
            raise ValueError("candidate SHA-256 fields must be 64 lowercase hex characters")
        if re.fullmatch(r"[0-9a-f]{7,64}", self.code_commit) is None:
            raise ValueError("code_commit must be a lowercase hexadecimal commit identity")
        if self.candidate_id and re.fullmatch(r"cand_[0-9a-f]{24}", self.candidate_id) is None:
            raise ValueError("candidate_id has an invalid format")
        if self.candidate_id:
            payload = asdict(self)
            payload.pop("candidate_id")
            expected_candidate_id = f"cand_{canonical_sha256(payload)[:24]}"
            if self.candidate_id != expected_candidate_id:
                raise ValueError("candidate_id does not match Candidate Canonical content")

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
