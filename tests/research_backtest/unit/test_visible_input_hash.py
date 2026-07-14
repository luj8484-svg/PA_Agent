import inspect
from dataclasses import replace

from pa_agent.research_backtest.domain.validation import VisibleValidationState
from pa_agent.research_backtest.strategy.visible_input import decision_visible_input_hash
from tests.research_backtest.helpers import INTERVAL_MS, make_bars


def _hash(daily, four_hour, decision_time):
    return decision_visible_input_hash(
        symbol="BTCUSDT",
        decision_time_utc_ms=decision_time,
        training_start_utc_ms=250 * INTERVAL_MS["1d"],
        daily_bars=daily,
        four_hour_bars=four_hour,
        validation_state=VisibleValidationState(),
    )


def test_visible_hash_ignores_future_data_and_input_order():
    daily = make_bars(interval="1d", count=252)
    four_hour = make_bars(interval="4h", count=110)
    decision_time = four_hour[104].close_time_utc_ms
    expected = _hash(daily, four_hour, decision_time)

    changed_future = list(four_hour)
    changed_future[109] = replace(changed_future[109], close=changed_future[109].close + 999)

    assert _hash(list(reversed(daily)), list(reversed(four_hour)), decision_time) == expected
    assert _hash(daily, changed_future, decision_time) == expected


def test_visible_hash_changes_when_visible_validation_state_changes():
    daily = make_bars(interval="1d", count=250)
    four_hour = make_bars(interval="4h", count=100)
    decision_time = four_hour[-1].close_time_utc_ms
    valid = _hash(daily, four_hour, decision_time)
    invalid = decision_visible_input_hash(
        symbol="BTCUSDT",
        decision_time_utc_ms=decision_time,
        training_start_utc_ms=250 * INTERVAL_MS["1d"],
        daily_bars=daily,
        four_hour_bars=four_hour,
        validation_state=VisibleValidationState(four_hour_native_valid=False),
    )

    assert valid != invalid


def test_visible_hash_api_has_no_execution_or_acquisition_inputs():
    parameters = set(inspect.signature(decision_visible_input_hash).parameters)

    assert not any("execution" in name or "acquisition" in name for name in parameters)
    assert "strategy_data_content_hash" not in parameters
