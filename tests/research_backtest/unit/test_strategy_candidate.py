import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass, replace
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.candidates import candidate_id_for, strategy_candidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.domain.enums import MarketReason, MarketView, TrendState
from pa_agent.research_backtest.domain.failures import validation_failure
from pa_agent.research_backtest.domain.validation import VisibleValidationState
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
from pa_agent.research_backtest.strategy.candidate_factory import build_candidate
from tests.research_backtest.helpers import INTERVAL_MS, make_bars

FIXTURE = Path("tests/research_backtest/fixtures/strategy_golden_v1.json")
FULL_CANDIDATE_FIXTURE = Path("tests/research_backtest/fixtures/strategy_candidate_golden_v1.json")


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


def _reference_canonical_value(value):
    if is_dataclass(value):
        return _reference_canonical_value(asdict(value))
    if isinstance(value, Enum):
        return _reference_canonical_value(value.value)
    if isinstance(value, Decimal):
        if value.is_zero():
            return "0"
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, Mapping):
        return {str(key): _reference_canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_reference_canonical_value(item) for item in value]
    return value


def _reference_canonical_bytes(value):
    return json.dumps(
        _reference_canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _build(daily, four_hour, training_start, decision_time):
    return build_candidate(
        symbol="BTCUSDT",
        daily_bars=daily,
        four_hour_bars=four_hour,
        training_start_utc_ms=training_start,
        decision_time_utc_ms=decision_time,
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
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


def test_complete_strategy_candidate_golden_v1_matches_canonical_bytes_hash_and_id():
    raw = FULL_CANDIDATE_FIXTURE.read_text(encoding="utf-8").strip()
    fixture = json.loads(raw)
    training_start, daily, four_hour, decision_time = _candidate_inputs()

    candidate = _build(daily, four_hour, training_start, decision_time)

    assert raw == canonical_dumps(fixture)
    assert candidate.canonical_json() == fixture["candidate_canonical_json"]
    assert candidate.decision_visible_input_hash == fixture["decision_visible_input_hash"]
    assert candidate.candidate_id == fixture["candidate_id"]


def test_complete_candidate_hashes_match_independent_stdlib_reference():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)
    visible_payload = {
        "decision_time_utc_ms": decision_time,
        "decision_visible_input_version": "DECISION_VISIBLE_INPUT_V1",
        "daily_bars": daily,
        "four_hour_bars": four_hour,
        "indicator_versions": {
            "atr": "ATR_WILDER_V1_FLOAT64",
            "config": "INDICATOR_CONFIG_V1",
            "donchian": "DONCHIAN_PREVIOUS_20_V1_DECIMAL",
            "ema": "EMA_RECURSIVE_V1_FLOAT64",
            "numeric_boundary": "FLOAT64_TO_DECIMAL_15SIG_HALF_EVEN_V1",
        },
        "pre_roll_policy_version": "PRE_ROLL_POLICY_V1_EXACT_250D_100X4H",
        "symbol": "BTCUSDT",
        "training_start_utc_ms": training_start,
        "visible_validation_state": {
            "daily_closed": True,
            "daily_native_valid": True,
            "four_hour_closed": True,
            "four_hour_native_valid": True,
        },
    }
    reference_visible_hash = hashlib.sha256(_reference_canonical_bytes(visible_payload)).hexdigest()
    candidate_payload = json.loads(candidate.canonical_json())
    candidate_id = candidate_payload.pop("candidate_id")
    reference_candidate_id = (
        "cand_" + hashlib.sha256(_reference_canonical_bytes(candidate_payload)).hexdigest()[:24]
    )

    assert candidate.decision_visible_input_hash == reference_visible_hash
    assert candidate_id == reference_candidate_id


def test_last_pre_roll_bar_cannot_generate_candidate_but_first_post_start_bar_can():
    training_start, daily, four_hour, _decision_time = _candidate_inputs()

    before_start = _build(
        daily,
        four_hour,
        training_start,
        training_start - 1,
    )
    first_post_start = _build(
        daily,
        four_hour,
        training_start,
        four_hour[100].close_time_utc_ms,
    )

    assert before_start.reason.value == "DECISION_BEFORE_TRAINING_START"
    assert first_post_start.decision_bar_open_time_utc_ms == training_start


def test_training_start_must_align_to_utc_daily_and_four_hour_boundaries():
    training_start, daily, four_hour, decision_time = _candidate_inputs()

    failure = _build(daily, four_hour, training_start + 1, decision_time)

    assert failure.reason.value == "INDICATOR_BOUNDARY_INVALID"
    assert failure.decision_visible_input_hash is not None
    assert ("training_start_mod_1d_ms", "1") in failure.observed_values
    assert ("training_start_mod_4h_ms", "1") in failure.observed_values


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


def test_visible_validation_state_has_no_historical_continuity_truth_source():
    field_names = {field.name for field in fields(VisibleValidationState)}

    assert "daily_continuous" not in field_names
    assert "four_hour_continuous" not in field_names


def test_candidate_schema_rejects_illegal_market_price_time_and_hash_combinations():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)

    invalid_changes = (
        {"market_reason": MarketReason.NO_BREAKOUT},
        {"trend_state": TrendState.BEAR},
        {"decision_close": Decimal("0")},
        {"donchian_high_previous_20": candidate.donchian_low_previous_20 - Decimal("1")},
        {"decision_bar_open_time_utc_ms": candidate.decision_time_utc_ms},
        {"decision_visible_input_hash": "not-a-sha256"},
        {"candidate_id": "cand_" + "0" * 24},
    )

    for changes in invalid_changes:
        with pytest.raises(ValueError):
            replace(candidate, **changes)


@pytest.mark.parametrize(
    "changes",
    (
        {"daily_close": Decimal("1")},
        {"ema50_daily": Decimal("1")},
    ),
)
def test_candidate_independently_rejects_trend_ema_contradictions(changes):
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)

    with pytest.raises(ValueError, match="trend state contradicts"):
        replace(candidate, **changes)


def test_candidate_rejects_empty_id_instead_of_bypassing_content_validation():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)

    with pytest.raises(ValueError, match="candidate_id"):
        replace(candidate, candidate_id="")


def test_candidate_id_hashes_every_non_id_field():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    candidate = _build(daily, four_hour, training_start, decision_time)
    values = asdict(candidate)
    for fixed_field in (
        "schema_version",
        "candidate_id",
        "strategy_id",
        "strategy_version",
        "decision_visible_input_version",
        "created_by",
    ):
        values.pop(fixed_field)
    values["decision_close"] = candidate.decision_close + Decimal("1")
    changed = strategy_candidate(**values)

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


def test_noncanonical_history_before_exact_pre_roll_is_discarded_before_validation():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    expected = _build(daily, four_hour, training_start, decision_time)
    older_daily = make_bars(
        interval="1d",
        count=1,
        start_utc_ms=-INTERVAL_MS["1d"],
    )
    older_daily[0] = replace(older_daily[0], close=Decimal("NaN"))

    actual = _build(
        older_daily + daily,
        four_hour,
        training_start,
        decision_time,
    )

    assert actual.canonical_json() == expected.canonical_json()
    assert actual.candidate_id == expected.candidate_id


def test_duplicate_in_discarded_segment_does_not_change_current_candidate():
    training_start, daily, _four_hour, _decision_time = _candidate_inputs()
    four_hour = make_bars(
        interval="4h",
        count=130,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    del four_hour[106]
    decision_time = four_hour[-1].close_time_utc_ms
    expected = _build(daily, four_hour, training_start, decision_time)

    actual = _build(
        [*daily],
        [four_hour[102], *four_hour],
        training_start,
        decision_time,
    )

    assert actual.canonical_json() == expected.canonical_json()
    assert actual.candidate_id == expected.candidate_id


def test_missing_pre_roll_returns_validation_failure_not_no_setup():
    training_start, daily, four_hour, decision_time = _candidate_inputs()

    failure = _build(daily[1:], four_hour, training_start, decision_time)

    assert failure.reason.value == "PRE_ROLL_INSUFFICIENT"
    assert failure.decision_visible_input_hash is not None
    assert ("pre_roll_1d_bars", "250") in failure.expected_values
    assert ("pre_roll_1d_bars", "249") in failure.observed_values
    assert ("pre_roll_4h_bars", "100") in failure.expected_values
    assert ("pre_roll_4h_bars", "100") in failure.observed_values
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
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )

    assert failure.reason.value == "INDICATOR_BOUNDARY_INVALID"


def test_gap_resets_segment_then_reports_warming_up_on_next_bar():
    training_start, daily, four_hour, _decision_time = _candidate_inputs()
    del four_hour[-3]
    first_after_gap_time = four_hour[-2].close_time_utc_ms
    second_after_gap_time = four_hour[-1].close_time_utc_ms

    first = _build(daily, four_hour, training_start, first_after_gap_time)
    second = _build(daily, four_hour, training_start, second_after_gap_time)
    expected_gap = (
        four_hour[-3].open_time_utc_ms + INTERVAL_MS["4h"],
        four_hour[-2].open_time_utc_ms - 1,
    )

    assert first.reason.value == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert first.decision_visible_input_hash is not None
    assert first.gap_intervals == (expected_gap,)
    assert ("4h_step_ms", str(INTERVAL_MS["4h"])) in first.expected_values
    assert ("4h_step_ms", str(2 * INTERVAL_MS["4h"])) in first.observed_values
    assert second.reason.value == "INDICATOR_WARMING_UP"
    assert second.decision_visible_input_hash is not None
    assert second.gap_intervals == (expected_gap,)
    assert ("continuous_1d_bars_min", "200") in second.expected_values
    assert ("continuous_4h_bars_min", "21") in second.expected_values
    assert ("continuous_4h_bars", "2") in second.observed_values


def test_candidate_recovers_after_post_gap_active_segment_finishes_warmup():
    training_start, daily, _four_hour, _decision_time = _candidate_inputs()
    four_hour = make_bars(
        interval="4h",
        count=130,
        start_utc_ms=training_start - 100 * INTERVAL_MS["4h"],
    )
    del four_hour[106]

    first_post_gap = _build(
        daily,
        four_hour,
        training_start,
        four_hour[106].close_time_utc_ms,
    )
    recovered = _build(
        daily,
        four_hour,
        training_start,
        four_hour[-1].close_time_utc_ms,
    )

    assert first_post_gap.reason.value == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert recovered.candidate_id.startswith("cand_")


def test_different_visible_failure_data_changes_id_but_future_data_does_not():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    missing_one = _build(daily[1:], four_hour, training_start, decision_time)
    missing_two = _build(daily[2:], four_hour, training_start, decision_time)
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
    same_history_with_future = _build(
        daily[1:] + future_daily,
        four_hour + future_four_hour,
        training_start,
        decision_time,
    )

    assert missing_one.failure_id != missing_two.failure_id
    assert missing_one.failure_id == same_history_with_future.failure_id
    assert (
        missing_one.decision_visible_input_hash
        == same_history_with_future.decision_visible_input_hash
    )


def test_duplicate_failure_identity_is_independent_of_equal_timestamp_input_order():
    training_start, daily, four_hour, decision_time = _candidate_inputs()
    duplicate = replace(
        four_hour[-2],
        high=four_hour[-2].high + Decimal("0.25"),
        close=four_hour[-2].close + Decimal("0.25"),
    )

    original_first = _build(
        daily,
        [*four_hour, duplicate],
        training_start,
        decision_time,
    )
    duplicate_first = _build(
        daily,
        [duplicate, *four_hour],
        training_start,
        decision_time,
    )

    assert original_first.reason.value == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert duplicate_first.reason.value == "DATA_SEGMENT_NOT_CONTINUOUS"
    assert original_first.failure_id == duplicate_first.failure_id
    assert original_first.decision_visible_input_hash == duplicate_first.decision_visible_input_hash


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
        indicator_config_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )

    assert failure.failure_id.startswith("val_")
    assert len(failure.failure_id) == 28


@pytest.mark.parametrize(
    "changes",
    (
        {"failure_id": ""},
        {"failure_id": "val_" + "0" * 24},
        {"schema_version": "VALIDATION_FAILURE_SCHEMA_V0"},
        {"indicator_config_hash": "not-a-sha256"},
        {"decision_visible_input_hash": "not-a-sha256"},
        {"gap_intervals": ((2, 1),)},
    ),
)
def test_validation_failure_rejects_illegal_schema_hash_id_and_gap_content(changes):
    failure = validation_failure(
        reason="INDICATOR_WARMING_UP",
        symbol="BTCUSDT",
        decision_time_utc_ms=1,
        affected_interval="4h",
        decision_visible_input_hash=None,
        expected_values=(("required", "20"),),
        observed_values=(("actual", "19"),),
        gap_intervals=(),
        indicator_config_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )

    with pytest.raises(ValueError):
        replace(failure, **changes)


def test_candidate_factory_api_has_no_wall_clock_or_execution_configuration():
    parameters = set(inspect.signature(build_candidate).parameters)

    assert not any("clock" in name or "execution" in name or "delay" in name for name in parameters)
    assert "strategy_data_content_hash" not in parameters
