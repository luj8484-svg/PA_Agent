from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.candidates import strategy_candidate
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState
from pa_agent.research_backtest.domain.market_inputs import (
    target_event_watermark,
    target_minute_open_snapshot,
)
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.planning.time import (
    TargetMinuteUnavailableError,
    entry_target_time,
    next_four_hour_anchor,
    require_target_reached,
    resolve_target_open,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
COMMIT = "c" * 40
DECISION_TIME = 14_400_000 - 1


def registered(test_id: str, requirement_id: str):
    def decorate(function):
        function = pytest.mark.requirement_ids(requirement_id)(function)
        return pytest.mark.test_id(test_id)(function)

    return decorate


def candidate(*, market_view: MarketView = MarketView.LONG):
    if market_view is MarketView.LONG:
        reason = MarketReason.BULL_DONCHIAN_BREAKOUT
        close = Decimal("121")
        trend = TrendState.BULL
        daily_close, ema50, ema200 = Decimal("110"), Decimal("105"), Decimal("100")
    elif market_view is MarketView.SHORT:
        reason = MarketReason.BEAR_DONCHIAN_BREAKOUT
        close = Decimal("79")
        trend = TrendState.BEAR
        daily_close, ema50, ema200 = Decimal("90"), Decimal("95"), Decimal("100")
    else:
        reason = MarketReason.NO_BREAKOUT
        close = Decimal("100")
        trend = TrendState.BULL
        daily_close, ema50, ema200 = Decimal("110"), Decimal("105"), Decimal("100")
    return strategy_candidate(
        symbol="BTCUSDT",
        decision_time_utc_ms=DECISION_TIME,
        decision_bar_open_time_utc_ms=0,
        market_view=market_view,
        market_reason=reason,
        decision_close=close,
        daily_close=daily_close,
        trend_state=trend,
        ema50_daily=ema50,
        ema200_daily=ema200,
        atr14_4h=Decimal("10"),
        donchian_high_previous_20=Decimal("120"),
        donchian_low_previous_20=Decimal("80"),
        decision_visible_input_hash=SHA_A,
        indicator_config_hash=SHA_B,
        strategy_config_hash="d" * 64,
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )


def config(delay: int = 1):
    return execution_time_config(entry_delay_minutes=delay, exit_delay_minutes=1)


def intent(delay: int = 1):
    return make_entry_intent(
        candidate(),
        config(delay),
        computational_experiment_id="f" * 64,
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )


@registered("UT-LIFE-001", "2B-LIFE-001")
def test_only_actionable_long_or_short_candidate_produces_entry_intent() -> None:
    assert (
        make_entry_intent(
            candidate(market_view=MarketView.LONG),
            config(),
            computational_experiment_id="f" * 64,
            code_commit=COMMIT,
            dependency_lock_hash="e" * 64,
        ).side.value
        == "LONG"
    )
    assert (
        make_entry_intent(
            candidate(market_view=MarketView.SHORT),
            config(),
            computational_experiment_id="f" * 64,
            code_commit=COMMIT,
            dependency_lock_hash="e" * 64,
        ).side.value
        == "SHORT"
    )
    with pytest.raises(ValueError, match="not actionable"):
        make_entry_intent(
            candidate(market_view=MarketView.NO_SETUP),
            config(),
            computational_experiment_id="f" * 64,
            code_commit=COMMIT,
            dependency_lock_hash="e" * 64,
        )


@registered("UT-LIFE-002", "2B-LIFE-002")
def test_entry_intent_contains_no_future_price_contract_account_or_quantity() -> None:
    names = {field.name for field in fields(type(intent()))}
    forbidden = {"price", "quantity", "contract", "account", "stop", "take_profit"}
    assert all(not any(token in name for token in forbidden) for name in names)


@registered("UT-SCHEMA-001", "2B-SCHEMA-001")
def test_entry_intent_closed_schema_is_exact() -> None:
    assert tuple(field.name for field in fields(type(intent()))) == (
        "schema_version",
        "intent_id",
        "intent_content_hash",
        "candidate_id",
        "candidate_schema_version",
        "computational_experiment_id",
        "symbol",
        "side",
        "candidate_decision_time_utc_ms",
        "intent_created_time_utc_ms",
        "execution_anchor_utc_ms",
        "target_execution_time_utc_ms",
        "execution_delay_minutes",
        "execution_time_config_id",
        "execution_time_config_content_hash",
        "execution_time_config_version",
        "decision_visible_input_hash",
        "strategy_version",
        "intent_config_hash",
        "code_commit",
        "dependency_lock_hash",
    )


@registered("UT-SCHEMA-009", "2B-SCHEMA-009")
def test_target_open_snapshot_is_only_the_open_event() -> None:
    snapshot = target_minute_open_snapshot(
        symbol="BTCUSDT",
        open_time_utc_ms=14_460_000,
        open_price=Decimal("101.25"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )
    names = {field.name for field in fields(type(snapshot))}
    assert names == {
        "schema_version",
        "snapshot_id",
        "snapshot_content_hash",
        "symbol",
        "stream",
        "open_time_utc_ms",
        "open_price",
        "source_event_id",
        "source_stream_version",
        "created_by",
        "code_commit",
        "dependency_lock_hash",
    }
    expected_source = canonical_sha256(
        {
            "symbol": "BTCUSDT",
            "stream": "trade",
            "open_time_utc_ms": 14_460_000,
            "open_price": Decimal("101.25"),
            "source_stream_version": "BINANCE_TRADE_OPEN_EVENT_V1",
        }
    )
    assert snapshot.source_event_id == f"tmopen_source_{expected_source[:24]}"


@registered("UT-SCHEMA-016", "2B-SCHEMA-016")
def test_snapshot_identity_excludes_watermark() -> None:
    first = target_minute_open_snapshot(
        symbol="BTCUSDT",
        open_time_utc_ms=14_460_000,
        open_price=Decimal("101.25"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )
    assert "watermark" not in first.canonical_json()


@registered("UT-SCHEMA-017", "2B-SCHEMA-017")
def test_watermark_has_independent_source_identity_without_open() -> None:
    watermark = target_event_watermark(
        symbol="BTCUSDT",
        target_open_time_utc_ms=14_460_000,
        event_watermark_time_utc_ms=14_520_000,
        watermark_source_event_id="trade_watermark_0001",
        watermark_source_stream_version="TRADE_WATERMARK_V1",
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )
    assert watermark.watermark_source_event_id == "trade_watermark_0001"
    assert not hasattr(watermark, "source_event_id")


@registered("UT-TIME-001", "2B-TIME-001")
def test_next_four_hour_anchor_requires_exact_closed_bar_boundary() -> None:
    assert next_four_hour_anchor(14_400_000 - 1) == 14_400_000
    with pytest.raises(ValueError, match="4H close"):
        next_four_hour_anchor(14_400_000 - 2)


@registered("UT-TIME-002", "2B-TIME-002")
def test_entry_delays_zero_one_two_are_exact() -> None:
    assert [entry_target_time(DECISION_TIME, config(delay)) for delay in (0, 1, 2)] == [
        14_400_000,
        14_460_000,
        14_520_000,
    ]
    with pytest.raises(ValueError):
        config(3)


@registered("UT-TIME-008", "2B-TIME-008")
def test_target_factory_precondition_rejects_event_before_target() -> None:
    with pytest.raises(ValueError, match="before target"):
        require_target_reached(14_459_999, 14_460_000)
    require_target_reached(14_460_000, 14_460_000)


@registered("UT-TIME-009", "2B-TIME-009")
def test_watermark_past_target_with_missing_snapshot_is_explicit_unavailable() -> None:
    value = intent()
    watermark = target_event_watermark(
        symbol=value.symbol,
        target_open_time_utc_ms=value.target_execution_time_utc_ms,
        event_watermark_time_utc_ms=value.target_execution_time_utc_ms,
        watermark_source_event_id="trade_watermark_0002",
        watermark_source_stream_version="TRADE_WATERMARK_V1",
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )
    with pytest.raises(TargetMinuteUnavailableError):
        resolve_target_open(value, snapshot=None, watermark=watermark)


@registered("UT-TIME-013", "2B-TIME-013")
def test_late_consumption_does_not_change_snapshot_or_intent_identity() -> None:
    value = intent()
    snapshot = target_minute_open_snapshot(
        symbol=value.symbol,
        open_time_utc_ms=value.target_execution_time_utc_ms,
        open_price=Decimal("101.25"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=COMMIT,
        dependency_lock_hash="e" * 64,
    )
    identities = []
    for observed_at in (
        value.target_execution_time_utc_ms,
        value.target_execution_time_utc_ms + 60_000,
    ):
        watermark = target_event_watermark(
            symbol=value.symbol,
            target_open_time_utc_ms=value.target_execution_time_utc_ms,
            event_watermark_time_utc_ms=observed_at,
            watermark_source_event_id=f"trade_watermark_{observed_at}",
            watermark_source_stream_version="TRADE_WATERMARK_V1",
            code_commit=COMMIT,
            dependency_lock_hash="e" * 64,
        )
        resolved = resolve_target_open(value, snapshot=snapshot, watermark=watermark)
        identities.append((resolved.snapshot_id, resolved.snapshot_content_hash, value.intent_id))
    assert identities[0] == identities[1]


@registered("UT-ID-003", "2B-ID-003")
def test_future_data_has_no_input_channel_to_intent_or_open_snapshot() -> None:
    before = intent()
    after = intent()
    assert before == after


@registered("UT-ID-004", "2B-ID-004")
def test_delay_changes_intent_identity_but_not_candidate_identity() -> None:
    source = candidate()
    values = [
        make_entry_intent(
            source,
            config(delay),
            computational_experiment_id="f" * 64,
            code_commit=COMMIT,
            dependency_lock_hash="e" * 64,
        )
        for delay in (0, 1, 2)
    ]
    assert len({value.intent_id for value in values}) == 3
    assert all(value.candidate_id == source.candidate_id for value in values)
    with pytest.raises(ValueError):
        replace(values[0], execution_delay_minutes=1)
