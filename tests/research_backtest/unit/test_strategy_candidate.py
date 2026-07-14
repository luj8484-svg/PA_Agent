import inspect
import json
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.candidates import candidate_id_for
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState
from pa_agent.research_backtest.domain.failures import validation_failure
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
from pa_agent.research_backtest.strategy.candidate_factory import build_candidate
from tests.research_backtest.helpers import INTERVAL_MS, make_bars

FIXTURE = Path("tests/research_backtest/fixtures/strategy_golden_v1.json")


def _candidate_inputs():
    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=251)
    four_hour = make_bars(
        interval="4h",
        count=106,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    previous_close = four_hour[-2].close
    four_hour[-1] = replace(
        four_hour[-1],
        open=previous_close + Decimal("4"),
        high=previous_close + Decimal("7"),
        low=previous_close + Decimal("3"),
        close=previous_close + Decimal("6"),
    )
    return training_start, daily, four_hour, four_hour[-1].close_time_utc_ms


def _build(daily, four_hour, training_start, decision_time):
    return build_candidate(
        symbol="BTCUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_time_utc_ms=decision_time,
        code_commit="abc123",
        dependency_lock_hash="lock123",
    )


def test_strategy_golden_truth_table_is_exact_and_canonical():
    raw = FIXTURE.read_text(encoding="utf-8").strip()
    fixture = json.loads(raw)
    assert raw == canonical_dumps(fixture)
    for case in fixture["cases"]:
        decision = classify_market(
            trend_state=TrendState(case["trend"]),
            current_close=Decimal(case["close"]),
            donchian_high=Decimal(fixture["donchian_high"]),
            donchian_low=Decimal(fixture["donchian_low"]),
        )
        assert decision.market_view.value == case["expected_view"]
        assert decision.market_reason.value == case["expected_reason"]


def test_candidate_factory_builds_long_from_visible_closed_bars():
    training_start, daily, four_hour, decision_time = _candidate_inputs()

    candidate = _build(daily, four_hour, training_start, decision_time)

    assert candidate.market_view is MarketView.LONG
    assert candidate.market_reason is MarketReason.BULL_DONCHIAN_BREAKOUT
    assert candidate.trend_state is TrendState.BULL
    assert candidate.candidate_id.startswith("cand_")
    assert len(candidate.candidate_id) == 29


def test_candidate_schema_is_frozen_and_contains_no_execution_or_contract_fields():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)
    field_names = {field.name for field in fields(candidate)}
    forbidden = {
        "entry_intent",
        "execution_anchor",
        "execution_delay_minutes",
        "execution_delay_version",
        "strategy_data_content_hash",
        "contract_rule_version",
        "quantity",
        "position",
    }

    assert forbidden.isdisjoint(field_names)
    with pytest.raises(FrozenInstanceError):
        candidate.symbol = "ETHUSDT"


def test_candidate_id_hashes_every_non_id_field():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)
    changed = replace(candidate, decision_close=candidate.decision_close + Decimal("1"))

    assert candidate_id_for(candidate) == candidate.candidate_id
    assert candidate_id_for(changed) != candidate.candidate_id


def test_future_bars_and_input_order_do_not_change_past_candidate_bytes_or_id():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    expected = _build(daily, four_hour, training_start, decision_time)
    future_daily = make_bars(
        interval="1d",
        count=2,
        start_utc_ms=daily[-1].open_time_utc_ms + INTERVAL_MS["1d"],
    )
    future_four_hour = make_bars(
        interval="4h",
        count=2,
        start_utc_ms=four_hour[-1].open_time_utc_ms + INTERVAL_MS["4h"],
    )

    actual = _build(
        list(reversed(daily + future_daily)),
        list(reversed(four_hour + future_four_hour)),
        training_start,
        decision_time,
    )

    assert actual.canonical_json() == expected.canonical_json()
    assert actual.candidate_id == expected.candidate_id


def test_history_before_exact_pre_roll_does_not_change_candidate_seed_or_id():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    expected = _build(daily, four_hour, training_start, decision_time)
    older_daily = make_bars(
        interval="1d",
        count=10,
        start_utc_ms=-10 * INTERVAL_MS["1d"],
    )
    older_four_hour = make_bars(
        interval="4h",
        count=10,
        start_utc_ms=four_hour[0].open_time_utc_ms - 10 * INTERVAL_MS["4h"],
    )

    actual = _build(
        older_daily + daily,
        older_four_hour + four_hour,
        training_start,
        decision_time,
    )

    assert actual.canonical_json() == expected.canonical_json()
    assert actual.candidate_id == expected.candidate_id


def test_missing_pre_roll_returns_validation_failure_not_no_setup():
    training_start, daily, four_hour, decision_time = _candidate_inputs()

    failure = _build(daily[1:], four_hour, training_start, decision_time)

    assert failure.reason.value == "PRE_ROLL_INSUFFICIENT"
    assert not hasattr(failure, "market_view")
    with pytest.raises(FrozenInstanceError):
        failure.symbol = "ETHUSDT"


def test_wrong_visible_interval_is_validation_failure():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    four_hour[0] = replace(four_hour[0], interval="1m")

    failure = _build(daily, four_hour, training_start, decision_time)

    assert failure.reason.value == "INDICATOR_BOUNDARY_INVALID"


def test_candidate_factory_rejects_symbols_outside_btc_eth_scope():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    daily = [replace(bar, symbol="XRPUSDT") for bar in daily]
    four_hour = [replace(bar, symbol="XRPUSDT") for bar in four_hour]

    failure = build_candidate(
        symbol="XRPUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_time_utc_ms=decision_time,
        code_commit="abc123",
        dependency_lock_hash="lock123",
    )

    assert failure.reason.value == "INDICATOR_BOUNDARY_INVALID"


def test_gap_resets_segment_then_reports_warming_up_on_next_bar():
    training_start, daily, four_hour, _decision_time = _candidate_inputs()
    del four_hour[-3]
    first_after_gap_time = four_hour[-2].close_time_utc_ms
    second_after_gap_time = four_hour[-1].close_time_utc_ms

    first = _build(daily, four_hour, training_start, first_after_gap_time)
    second = _build(daily, four_hour, training_start, second_after_gap_time)

    assert first.reason.value == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert second.reason.value == "INDICATOR_WARMING_UP"


def test_validation_failure_id_hashes_all_non_id_fields():
    failure = validation_failure(
        reason="INDICATOR_WARMING_UP",
        symbol="BTCUSDT",
        decision_time_utc_ms=1,
        affected_interval="4h",
        decision_visible_input_hash=None,
        expected_values=(("required", "20"),),
        observed_values=(("actual", "19"),),
        gap_intervals=(),
        indicator_config_hash="config",
        code_commit="abc",
        dependency_lock_hash="lock",
    )

    assert failure.failure_id.startswith("val_")
    assert len(failure.failure_id) == 28


def test_candidate_factory_api_has_no_wall_clock_or_execution_configuration():
    parameters = set(inspect.signature(build_candidate).parameters)

    assert not any("clock" in name or "execution" in name or "delay" in name for name in parameters)
    assert "strategy_data_content_hash" not in parameters
