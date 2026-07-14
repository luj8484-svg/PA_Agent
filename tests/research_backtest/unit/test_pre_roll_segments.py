import pytest

from pa_agent.research_backtest.domain.validation import highest_priority_failure
from pa_agent.research_backtest.strategy.pre_roll import (
    PreRollSelectionError,
    active_segment,
    select_exact_pre_roll,
)
from tests.research_backtest.helpers import INTERVAL_MS, make_bars


def _pre_roll_inputs():
    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=250)
    four_hour = make_bars(
        interval="4h",
        count=100,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    return training_start, daily, four_hour


def test_pre_roll_selects_exactly_250_daily_and_100_four_hour_bars():
    training_start, daily, four_hour = _pre_roll_inputs()
    older_daily = make_bars(
        interval="1d",
        count=5,
        start_utc_ms=-5 * INTERVAL_MS["1d"],
    )

    selection = select_exact_pre_roll(
        older_daily + daily,
        list(reversed(four_hour)),
        training_start_utc_ms=training_start,
    )

    assert selection.daily == tuple(daily)
    assert selection.four_hour == tuple(four_hour)


@pytest.mark.parametrize(("daily_count", "four_hour_count"), [(249, 100), (250, 99)])
def test_pre_roll_rejects_even_one_missing_bar(daily_count, four_hour_count):
    training_start = 250 * INTERVAL_MS["1d"]
    daily = make_bars(interval="1d", count=daily_count)
    four_hour = make_bars(
        interval="4h",
        count=four_hour_count,
        start_utc_ms=training_start - four_hour_count * INTERVAL_MS["4h"],
    )

    with pytest.raises(PreRollSelectionError) as error:
        select_exact_pre_roll(daily, four_hour, training_start_utc_ms=training_start)

    assert error.value.reason == "PRE_ROLL_INSUFFICIENT"


def test_pre_roll_rejects_gap_in_exact_window():
    training_start, _daily, four_hour = _pre_roll_inputs()
    daily_with_gap = make_bars(
        interval="1d",
        count=251,
        start_utc_ms=-INTERVAL_MS["1d"],
    )
    del daily_with_gap[120]

    with pytest.raises(PreRollSelectionError) as error:
        select_exact_pre_roll(
            daily_with_gap,
            four_hour,
            training_start_utc_ms=training_start,
        )

    assert error.value.reason == "DATA_SEGMENT_NOT_CONTINUOUS"


def test_active_segment_resets_at_gap_and_marks_only_first_post_gap_decision():
    bars = make_bars(interval="4h", count=5)
    del bars[2]

    first_post_gap = active_segment(
        bars,
        interval_ms=INTERVAL_MS["4h"],
        decision_time_utc_ms=bars[2].close_time_utc_ms,
    )
    second_post_gap = active_segment(
        bars,
        interval_ms=INTERVAL_MS["4h"],
        decision_time_utc_ms=bars[3].close_time_utc_ms,
    )

    assert first_post_gap.bars == (bars[2],)
    assert first_post_gap.gap_at_decision is True
    assert second_post_gap.bars == (bars[2], bars[3])
    assert second_post_gap.gap_at_decision is False


def test_failure_priority_is_frozen():
    assert highest_priority_failure(
        {"INDICATOR_WARMING_UP", "DATA_SEGMENT_NOT_CONTINUOUS", "PRE_ROLL_INSUFFICIENT"}
    ) == "PRE_ROLL_INSUFFICIENT"
    assert highest_priority_failure(
        {"INDICATOR_WARMING_UP", "DATA_SEGMENT_NOT_CONTINUOUS"}
    ) == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert highest_priority_failure({"INDICATOR_WARMING_UP"}) == "INDICATOR_WARMING_UP"
