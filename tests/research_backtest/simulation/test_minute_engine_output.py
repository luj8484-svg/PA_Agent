from __future__ import annotations

from dataclasses import dataclass, fields, replace
from decimal import Decimal
from types import SimpleNamespace

from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
from tests.research_backtest.simulation.test_funding_liquidation import maintenance, position
from tests.research_backtest.simulation.test_inputs_and_invalid import bar


@dataclass(frozen=True)
class FakeCandidate:
    candidate_id: str
    decision_time_utc_ms: int


def config(**changes):
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    payload = config_payload() | changes
    return make_simulation_config(**payload)


def minute(open_time: int = 60_000):
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

    trade = replace(bar(), open_time_utc_ms=open_time, close_time_utc_ms=open_time + 59_999)
    mark = replace(bar(), open_time_utc_ms=open_time, close_time_utc_ms=open_time + 59_999)
    return MinuteInputSlice(open_time, (trade,), (mark,), (), ())


def dependencies(**changes):
    from pa_agent.research_backtest.simulation.engine import EngineDependencies
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    defaults = {
        "planners": PlannerDependencies(None, None, None, None),
        "entry_intent_factory": None,
        "exit_intent_factory": None,
        "planning_evidence_factory": lambda *_: None,
        "maintenance_evidence_factory": lambda *_: maintenance(),
        "execution_cost_factory": lambda *_: SimpleNamespace(
            slippage_rate=Decimal("0.001"),
            fee_rate=Decimal("0.0005"),
            tick_size=Decimal("0.1"),
        ),
    }
    return EngineDependencies(**(defaults | changes))


def test_valid_empty_minute_executes_all_14_stages() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.versions import EVENT_STAGES

    result = process_minute(initial_engine_state(config()), minute(), config(), dependencies())
    assert tuple(event.stage for event in result.events) == EVENT_STAGES
    assert len(result.equity_points) == 1
    assert result.equity_points[0].equity == Decimal("10000")


def test_invalid_mark_gap_stops_without_equity() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

    state = replace(initial_engine_state(config()), positions=(position(),))
    result = process_minute(
        state,
        MinuteInputSlice(60_000, (bar(),), (), (), ()),
        config(),
        dependencies(),
    )
    assert result.state.path_state.value == "INVALID"
    assert tuple(event.stage for event in result.events) == (
        "LOAD_CLOSED_INPUTS",
        "FAIL_CLOSED_DATA_GATE",
    )
    assert result.equity_points == ()


def test_funding_is_applied_before_open_gate() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import FundingRecord

    pos = position()
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    record = FundingRecord("f1", "BTCUSDT", 60_000, Decimal("0.01"), Decimal("100"), "a" * 64)
    value = minute()
    calm_trade = replace(value.trade_bars[0], low=Decimal("95"), high=Decimal("105"))
    calm_mark = replace(value.mark_bars[0], low=Decimal("95"), high=Decimal("105"))
    value = replace(
        value,
        trade_bars=(calm_trade,),
        mark_bars=(calm_mark,),
        funding_records=(record,),
        funding_expected=True,
    )
    result = process_minute(state, value, config(), dependencies())
    assert result.state.wallet_balance == Decimal("9998")
    assert result.state.locked_funding_reserve == Decimal("4")
    funding_index = next(i for i, event in enumerate(result.events) if event.kind == "FUNDING")
    open_index = next(
        i for i, event in enumerate(result.events) if event.stage == "OPEN_GAP_PROTECTIVE_GATE"
    )
    assert funding_index < open_index


def test_funding_and_time_exit_same_minute_orders_funding_first() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import FundingRecord
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    intent = SimpleNamespace(
        intent_id="time-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
        target_execution_time_utc_ms=60_000,
    )
    plan = SimpleNamespace(
        plan_id="time-exit-plan",
        intent_id=intent.intent_id,
        origin_candidate_id=pos.origin_candidate_id,
        position_id=pos.position_id,
        symbol=pos.symbol,
        position_side=Side.LONG,
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
        target_execution_time_utc_ms=60_000,
        quantity=pos.quantity,
        expected_exit_fill_price=Decimal("100"),
        expected_exit_fee=Decimal("0"),
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(intent,),
        pending_exit_reason_matches=((intent.intent_id, (ScheduledExitReason.TIME_EXIT,)),),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    funding = FundingRecord(
        "funding-time-exit",
        "BTCUSDT",
        60_000,
        Decimal("0.01"),
        Decimal("100"),
        "a" * 64,
    )
    value = replace(minute(), funding_records=(funding,), funding_expected=True)
    result = process_minute(
        state,
        value,
        config(),
        dependencies(
            planners=PlannerDependencies(None, None, lambda *_: plan, lambda value: value)
        ),
    )
    assert result.state.positions == ()
    assert result.fills[0].selected_exit_reason is ScheduledExitReason.TIME_EXIT
    assert result.ledger_entries[0].kind.value == "FUNDING"
    assert next(event for event in result.events if event.kind == "FUNDING").stage == (
        "FUNDING_SETTLEMENT"
    )
    from tests.research_backtest.simulation.golden_support import assert_full_golden

    assert_full_golden(
        "FUNDING_WITH_TIME_EXIT",
        input_fixture=(state, value, plan),
        event_sequence=result.events,
        ledger=result.ledger_entries,
        fill_trade={"fills": result.fills, "trades": result.trades},
        equity=result.equity_points,
        path_result=result.state,
    )


def test_funding_reserve_exceeded_is_precommit_atomic_invalid() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import (
        FundingRecord,
        FundingReserveExceeded,
    )
    from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent

    pos = replace(position(), remaining_funding_reserve=Decimal("1"))
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    record = FundingRecord("f-over", "BTCUSDT", 60_000, Decimal("0.01"), Decimal("100"), "a" * 64)
    value = replace(minute(), funding_records=(record,), funding_expected=True)
    result = process_minute(state, value, config(), dependencies())
    assert result.state.path_state.value == "INVALID"
    assert result.state.wallet_balance == state.wallet_balance
    assert result.state.locked_funding_reserve == state.locked_funding_reserve
    assert result.state.positions == state.positions
    assert result.ledger_entries == ()
    assert isinstance(result.planning_outputs[0], FundingReserveExceeded)
    assert result.planning_outputs[0].funding_record_id == "f-over"
    assert isinstance(result.planning_outputs[-1], PathInvalidEvent)
    from tests.research_backtest.simulation.golden_support import assert_full_golden

    assert_full_golden(
        "FUNDING_RESERVE_EXCEEDED",
        input_fixture=(state, value),
        event_sequence=result.events,
        ledger=result.ledger_entries,
        fill_trade={"fills": result.fills, "trades": result.trades},
        equity=result.equity_points,
        path_result=(result.state, result.planning_outputs[-1]),
    )


def test_open_gap_liquidation_cancels_due_scheduled_exit() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(),
        initial_margin=Decimal("2"),
        isolated_margin_balance=Decimal("2"),
        stop_trigger_price=Decimal("105"),
        take_profit_trigger_price=Decimal("95"),
    )
    due_exit = SimpleNamespace(
        intent_id="exit-intent",
        position_id=pos.position_id,
        symbol=pos.symbol,
        target_execution_time_utc_ms=60_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(due_exit,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    calls: list[object] = []
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    deps = dependencies(
        planners=PlannerDependencies(
            None,
            None,
            lambda *_: calls.append("scheduled") or object(),
            lambda value: value,
        )
    )
    result = process_minute(state, minute(), config(), deps)
    assert result.state.positions == ()
    assert calls == []
    protective = [fill for fill in result.fills if fill.selected_exit_reason is None]
    assert len(protective) == 1
    assert any(event.kind == "SCHEDULED_EXIT_CANCELLED" for event in result.events)
    from tests.research_backtest.simulation.golden_support import assert_full_golden

    assert_full_golden(
        "OPEN_LIQUIDATION_PRIORITY",
        input_fixture=(state, minute()),
        event_sequence=result.events,
        ledger=result.ledger_entries,
        fill_trade={"fills": result.fills, "trades": result.trades},
        equity=result.equity_points,
        path_result=result.state,
    )


def test_trend_exit_and_open_stop_executes_stop_only() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(), stop_trigger_price=Decimal("105"), take_profit_trigger_price=Decimal("120")
    )
    intent = SimpleNamespace(
        intent_id="trend-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        scheduled_exit_reason=ScheduledExitReason.TREND_EXIT,
        target_execution_time_utc_ms=60_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(intent,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(state, minute(), config(), dependencies())
    assert len(result.fills) == 1
    assert result.fills[0].plan_id.endswith(":STOP")
    assert result.state.positions == ()
    assert any(event.kind == "SCHEDULED_EXIT_CANCELLED" for event in result.events)


def test_scheduled_exit_and_open_tp_executes_tp_only() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("95")
    )
    intent = SimpleNamespace(
        intent_id="scheduled-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
        target_execution_time_utc_ms=60_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(intent,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(state, minute(), config(), dependencies())
    assert len(result.fills) == 1
    assert result.fills[0].plan_id.endswith(":TAKE_PROFIT")
    assert result.state.positions == ()
    assert any(event.kind == "SCHEDULED_EXIT_CANCELLED" for event in result.events)


def test_halt_does_not_end_processing_and_separates_times() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.halt import apply_halt

    halted = apply_halt(initial_engine_state(config()), 60_000, "DRAWDOWN")
    result = process_minute(
        halted, minute(120_000), config(simulation_end_exit_open_utc_ms=180_000), dependencies()
    )
    assert result.state.path_state.value == "HALTED"
    assert result.state.halt_trigger_time_utc_ms == 60_000
    assert result.state.final_processed_time_utc_ms == 120_000
    assert len(result.equity_points) == 1


def test_halt_position_exits_within_two_processed_minutes() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.halt import apply_halt
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    cfg = config(simulation_end_exit_open_utc_ms=180_000)
    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    state = replace(
        apply_halt(initial_engine_state(cfg), 60_000, "TEST_HALT"),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )

    def exit_factory(actual_position, reasons, event_time, _state):
        assert reasons == (ScheduledExitReason.HALT_EXIT,)
        return SimpleNamespace(
            intent_id="halt-exit-intent",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            scheduled_exit_reason=ScheduledExitReason.HALT_EXIT,
            target_execution_time_utc_ms=event_time + 1,
        )

    first = process_minute(
        state,
        minute(60_000),
        cfg,
        dependencies(
            exit_intent_factory=exit_factory,
            maintenance_evidence_factory=lambda *_: replace(
                maintenance(), effective_end_utc_ms=180_000
            ),
        ),
    )
    plan = SimpleNamespace(
        plan_id="halt-exit-plan",
        intent_id="halt-exit-intent",
        origin_candidate_id=pos.origin_candidate_id,
        position_id=pos.position_id,
        symbol=pos.symbol,
        position_side=Side.LONG,
        scheduled_exit_reason=ScheduledExitReason.HALT_EXIT,
        target_execution_time_utc_ms=120_000,
        quantity=pos.quantity,
        expected_exit_fill_price=Decimal("100"),
        expected_exit_fee=Decimal("0"),
    )
    second = process_minute(
        first.state,
        minute(120_000),
        cfg,
        dependencies(
            planners=PlannerDependencies(None, None, lambda *_: plan, lambda value: value),
            exit_intent_factory=exit_factory,
            maintenance_evidence_factory=lambda *_: replace(
                maintenance(), effective_end_utc_ms=180_000
            ),
        ),
    )
    assert second.state.positions == ()
    assert second.state.flat_after_halt_time_utc_ms == 120_000
    assert len(second.fills) == 1
    from tests.research_backtest.simulation.golden_support import assert_full_golden

    assert_full_golden(
        "HALT_DRAIN",
        input_fixture=(state, minute(60_000), minute(120_000), plan),
        event_sequence=(first.events, second.events),
        ledger=(first.ledger_entries, second.ledger_entries),
        fill_trade={
            "fills": (first.fills, second.fills),
            "trades": (first.trades, second.trades),
        },
        equity=(first.equity_points, second.equity_points),
        path_result=second.state,
    )


def test_complete_run_is_deterministic_and_has_at_most_two_paths() -> None:
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.identity import canonical_2c_sha256
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs

    inputs = SimulationInputs((minute(0), minute(60_000), minute(120_000)), (), ())
    cfg = config(simulation_end_exit_open_utc_ms=120_000)
    first = run_simulation(inputs, cfg, dependencies())
    second = run_simulation(inputs, cfg, dependencies())
    assert len(first.paths) == 2
    assert canonical_2c_sha256(first) == canonical_2c_sha256(second)
    assert all(len(path.minute_results) == 3 for path in first.paths)


def test_complete_run_requires_contiguous_start_through_exit_open() -> None:
    import pytest

    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs

    inputs = SimulationInputs((minute(0), minute(120_000)), (), ())
    with pytest.raises(ValueError, match="contiguous"):
        run_simulation(
            inputs,
            config(simulation_end_exit_open_utc_ms=120_000),
            dependencies(),
        )


def test_complete_run_cannot_finish_valid_with_open_position() -> None:
    from pa_agent.research_backtest.domain.enums import Side
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    candidate = FakeCandidate(candidate_id="candidate", decision_time_utc_ms=0)
    intent = SimpleNamespace(
        intent_id="entry-intent",
        symbol="BTCUSDT",
        target_execution_time_utc_ms=60_000,
    )
    plan = SimpleNamespace(
        plan_id="entry-plan",
        candidate_id="candidate",
        symbol="BTCUSDT",
        side=Side.LONG,
        target_execution_time_utc_ms=60_000,
        quantity=Decimal("1"),
        expected_entry_fill_price=Decimal("100"),
        entry_fee=Decimal("0"),
        initial_margin=Decimal("100"),
        stop_trigger_price=Decimal("80"),
        take_profit_trigger_price=Decimal("120"),
        exit_fee_reserve=Decimal("0"),
        funding_reserve=Decimal("0"),
        funding_event_upper_bound=0,
        maximum_exit_time_utc_ms=999_999,
        required_cash=Decimal("100"),
        planned_risk=Decimal("20"),
    )
    result = run_simulation(
        SimulationInputs((minute(60_000), minute(120_000)), (candidate,), ()),
        config(simulation_start_utc_ms=60_000, simulation_end_exit_open_utc_ms=120_000),
        dependencies(
            entry_intent_factory=lambda _: intent,
            planners=PlannerDependencies(
                lambda *_: "batch-inputs",
                lambda _: SimpleNamespace(audit_objects=(plan,), plans=(plan,)),
                None,
                None,
            ),
            maintenance_evidence_factory=lambda *_: replace(
                maintenance(), effective_end_utc_ms=180_000
            ),
        ),
    )
    assert all(path.path_result.path_state.value == "INVALID" for path in result.paths)
    assert all(
        path.path_result.invalid_reason == "EXPERIMENT_END_POSITION_OPEN" for path in result.paths
    )
    assert all(path.minute_results[-1].equity_points == () for path in result.paths)


def test_experiment_end_blocks_entry_planning() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    due_entry = SimpleNamespace(
        intent_id="entry", symbol="BTCUSDT", target_execution_time_utc_ms=120_000
    )
    state = replace(initial_engine_state(config()), pending_entry_intents=(due_entry,))
    deps = dependencies(
        planners=PlannerDependencies(
            lambda *_: (_ for _ in ()).throw(AssertionError("entry planned after end")),
            lambda x: x,
            None,
            None,
        )
    )
    result = process_minute(state, minute(120_000), config(), deps)
    assert any(event.kind == "EXPERIMENT_END_ENTRY_CANCELLED" for event in result.events)


def test_experiment_end_open_exits_existing_position_and_blocks_entry() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    cfg = config(simulation_end_exit_open_utc_ms=120_000)
    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    due_entry = SimpleNamespace(
        intent_id="blocked-entry", symbol="ETHUSDT", target_execution_time_utc_ms=120_000
    )
    state = replace(
        initial_engine_state(cfg),
        positions=(pos,),
        pending_entry_intents=(due_entry,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )

    def exit_factory(actual_position, reasons, event_time, _state):
        assert reasons == (ScheduledExitReason.EXPERIMENT_END,)
        return SimpleNamespace(
            intent_id="experiment-end-exit",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            scheduled_exit_reason=ScheduledExitReason.EXPERIMENT_END,
            target_execution_time_utc_ms=event_time + 1,
        )

    first = process_minute(
        state,
        minute(60_000),
        cfg,
        dependencies(exit_intent_factory=exit_factory),
    )
    plan = SimpleNamespace(
        plan_id="experiment-end-plan",
        intent_id="experiment-end-exit",
        origin_candidate_id=pos.origin_candidate_id,
        position_id=pos.position_id,
        symbol=pos.symbol,
        position_side=Side.LONG,
        scheduled_exit_reason=ScheduledExitReason.EXPERIMENT_END,
        target_execution_time_utc_ms=120_000,
        quantity=pos.quantity,
        expected_exit_fill_price=Decimal("100"),
        expected_exit_fee=Decimal("0"),
    )
    end_minute = minute(120_000)
    end_minute = replace(
        end_minute,
        trade_bars=(
            *end_minute.trade_bars,
            replace(end_minute.trade_bars[0], symbol="ETHUSDT"),
        ),
        mark_bars=(
            *end_minute.mark_bars,
            replace(end_minute.mark_bars[0], symbol="ETHUSDT"),
        ),
    )
    second = process_minute(
        first.state,
        end_minute,
        cfg,
        dependencies(
            planners=PlannerDependencies(None, None, lambda *_: plan, lambda value: value),
            exit_intent_factory=exit_factory,
            maintenance_evidence_factory=lambda *_: replace(
                maintenance(), effective_end_utc_ms=180_000
            ),
        ),
    )
    assert second.state.positions == ()
    assert second.fills[0].selected_exit_reason is ScheduledExitReason.EXPERIMENT_END
    assert any(event.kind == "EXPERIMENT_END_ENTRY_CANCELLED" for event in second.events)


def test_process_minute_calls_entry_batch_planner_once_for_btc_and_eth() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    due = (
        SimpleNamespace(intent_id="btc", symbol="BTCUSDT", target_execution_time_utc_ms=60_000),
        SimpleNamespace(intent_id="eth", symbol="ETHUSDT", target_execution_time_utc_ms=60_000),
    )
    cfg = config(simulation_end_exit_open_utc_ms=120_000)
    state = replace(initial_engine_state(cfg), pending_entry_intents=due)
    calls: list[tuple[object, ...]] = []

    def batch_factory(_state, intents, _evidence):
        calls.append(intents)
        return "batch-inputs"

    outcome = SimpleNamespace(audit_objects=("batch-audit",), plans=())
    minute_input = minute()
    minute_input = replace(
        minute_input,
        trade_bars=(
            *minute_input.trade_bars,
            replace(minute_input.trade_bars[0], symbol="ETHUSDT"),
        ),
        mark_bars=(*minute_input.mark_bars, replace(minute_input.mark_bars[0], symbol="ETHUSDT")),
    )
    result = process_minute(
        state,
        minute_input,
        cfg,
        dependencies(planners=PlannerDependencies(batch_factory, lambda _: outcome, None, None)),
    )
    assert len(calls) == 1
    assert tuple(item.symbol for item in calls[0]) == ("BTCUSDT", "ETHUSDT")
    assert "batch-audit" in result.planning_outputs


def test_post_plan_invariant_violation_invalidates_whole_entry_batch() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import (
        PlannerDependencies,
        build_entry_batch_planning_outcome,
    )
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs

    batch_inputs = _batch_inputs()
    outcome = build_entry_batch_planning_outcome(batch_inputs)
    original = outcome.plans[0]
    corrupted = SimpleNamespace(
        **{field.name: getattr(original, field.name) for field in fields(original)}
    )
    corrupted.required_cash = Decimal("10001")
    invalid_outcome = replace(outcome, plans=(corrupted,))
    due = tuple(item.intent for item in batch_inputs.items)
    cfg = config(simulation_end_exit_open_utc_ms=TARGET_TIME + 60_000)
    state = replace(initial_engine_state(cfg), pending_entry_intents=due)
    minute_input = minute(TARGET_TIME)
    minute_input = replace(
        minute_input,
        trade_bars=(
            *minute_input.trade_bars,
            replace(minute_input.trade_bars[0], symbol="ETHUSDT"),
        ),
        mark_bars=(
            *minute_input.mark_bars,
            replace(minute_input.mark_bars[0], symbol="ETHUSDT"),
        ),
    )
    result = process_minute(
        state,
        minute_input,
        cfg,
        dependencies(
            planners=PlannerDependencies(
                lambda *_: batch_inputs, lambda _: invalid_outcome, None, None
            )
        ),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.fills == ()
    assert result.planning_outputs[-1].reason == ("ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION")


def test_accepted_plan_and_path_invalid_rejection_produce_zero_batch_fills() -> None:
    from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason
    from pa_agent.research_backtest.domain.rejections import entry_intent_subject_ref
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import (
        PlannerDependencies,
        build_entry_batch_planning_outcome,
    )
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.execution.unit.test_rejection_matrix import reject
    from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs

    batch_inputs = _batch_inputs()
    outcome = build_entry_batch_planning_outcome(batch_inputs)
    rejection = reject(
        entry_intent_subject_ref(batch_inputs.items[1].intent),
        (ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,),
    )
    invalid_outcome = replace(outcome, execution_rejections=(rejection,))
    due = tuple(item.intent for item in batch_inputs.items)
    cfg = config(simulation_end_exit_open_utc_ms=TARGET_TIME + 60_000)
    state = replace(initial_engine_state(cfg), pending_entry_intents=due)
    minute_input = minute(TARGET_TIME)
    minute_input = replace(
        minute_input,
        trade_bars=(
            *minute_input.trade_bars,
            replace(minute_input.trade_bars[0], symbol="ETHUSDT"),
        ),
        mark_bars=(
            *minute_input.mark_bars,
            replace(minute_input.mark_bars[0], symbol="ETHUSDT"),
        ),
    )
    result = process_minute(
        state,
        minute_input,
        cfg,
        dependencies(
            planners=PlannerDependencies(
                lambda *_: batch_inputs,
                lambda _: invalid_outcome,
                None,
                None,
            )
        ),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.fills == ()
    assert result.ledger_entries == ()
    invalid = result.planning_outputs[-1]
    assert invalid.rejection_id == rejection.rejection_id
    assert invalid.rejection_disposition == "EXECUTION_PATH_INVALID"


def test_time_exit_intent_is_created_at_aligned_maximum_open() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(),
        maximum_exit_time_utc_ms=60_000,
        stop_trigger_price=Decimal("80"),
        take_profit_trigger_price=Decimal("120"),
    )
    state = replace(
        initial_engine_state(config(simulation_end_exit_open_utc_ms=180_000)),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )

    def exit_factory(actual_position, reasons, event_time, _state):
        assert reasons == (ScheduledExitReason.TIME_EXIT,)
        assert event_time == 60_000
        return SimpleNamespace(
            intent_id="time-exit",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            target_execution_time_utc_ms=120_000,
        )

    result = process_minute(
        state,
        minute(60_000),
        config(simulation_end_exit_open_utc_ms=180_000),
        dependencies(exit_intent_factory=exit_factory),
    )
    assert result.state.pending_exit_intents[0].intent_id == "time-exit"
    assert result.planning_outputs[0].intent_id == "time-exit"


def test_scheduled_exit_planning_rejection_invalidates_path() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    due = SimpleNamespace(
        intent_id="due-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        target_execution_time_utc_ms=60_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(due,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    rejection = SimpleNamespace(reason=SimpleNamespace(value="CONTRACT_RULE_UNAVAILABLE"))
    result = process_minute(
        state,
        minute(60_000),
        config(),
        dependencies(
            planners=PlannerDependencies(None, None, lambda *_: rejection, lambda value: value)
        ),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[0] is rejection
    assert result.planning_outputs[-1].reason == (
        "SCHEDULED_EXIT_PLANNING_REJECTED:CONTRACT_RULE_UNAVAILABLE"
    )


def test_canonical_manifest_is_acquisition_independent() -> None:
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from pa_agent.research_backtest.simulation.output import output_manifest

    result = run_simulation(
        SimulationInputs((minute(0), minute(60_000), minute(120_000)), (), ()),
        config(),
        dependencies(),
    )
    first = output_manifest(result)
    second = output_manifest(result)
    assert first == second
    assert first.simulation_run_id == result.simulation_run_id
    assert first.input_identity_hash == result.simulation_input_identity_hash
    assert first.config_hash == result.config_content_hash
    assert not hasattr(first, "acquisition_manifest_hash")


def test_future_intent_does_not_turn_flat_gap_into_invalid() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

    future = SimpleNamespace(
        intent_id="future", symbol="BTCUSDT", target_execution_time_utc_ms=120_000
    )
    state = replace(initial_engine_state(config()), pending_entry_intents=(future,))
    result = process_minute(
        state,
        MinuteInputSlice(60_000, (), (), (), ()),
        config(),
        dependencies(),
    )
    assert result.state.path_state.value == "VALID"
    assert len(result.equity_points) == 1


def test_future_scheduled_exit_intent_is_not_consumed_early() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    future = SimpleNamespace(
        intent_id="future-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        target_execution_time_utc_ms=120_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(future,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(state, minute(60_000), config(), dependencies())
    assert result.state.pending_exit_intents == (future,)


def test_intraminute_protective_exit_cancels_future_scheduled_intent() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = replace(
        position(), stop_trigger_price=Decimal("95"), take_profit_trigger_price=Decimal("120")
    )
    future = SimpleNamespace(
        intent_id="future-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        target_execution_time_utc_ms=120_000,
    )
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        pending_exit_intents=(future,),
        pending_exit_reason_matches=(("future-exit", ()),),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(state, minute(60_000), config(), dependencies())
    assert result.state.positions == ()
    assert result.state.pending_exit_intents == ()
    assert result.state.pending_exit_reason_matches == ()
    assert any(event.kind == "SCHEDULED_EXIT_CANCELLED" for event in result.events)


def test_missing_maintenance_factory_result_is_invalid_not_exception() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute

    pos = position()
    state = replace(
        initial_engine_state(config()),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(
        state,
        minute(),
        config(),
        dependencies(maintenance_evidence_factory=lambda *_: None),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[-1].reason == "MAINTENANCE_EVIDENCE_UNAVAILABLE"


def test_missing_trend_evidence_at_closed_4h_boundary_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

    pos = position()
    state = replace(
        initial_engine_state(config(simulation_end_exit_open_utc_ms=28_800_000)),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    trade = replace(bar(), open_time_utc_ms=14_340_000, close_time_utc_ms=14_399_999)
    mark = replace(bar(), open_time_utc_ms=14_340_000, close_time_utc_ms=14_399_999)
    result = process_minute(
        state,
        MinuteInputSlice(14_340_000, (trade,), (mark,), (), ()),
        config(simulation_end_exit_open_utc_ms=28_800_000),
        dependencies(),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.equity_points == ()
    assert result.planning_outputs[-1].reason == "TREND_EVIDENCE_UNAVAILABLE:BTCUSDT"


def test_closed_4h_trend_loss_creates_scheduled_exit_intent() -> None:
    from pa_agent.research_backtest.domain.enums import TrendState
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice
    from pa_agent.research_backtest.simulation.planning import TrendEvidence

    pos = replace(position(), maximum_exit_time_utc_ms=99_999_999)
    state = replace(
        initial_engine_state(config(simulation_end_exit_open_utc_ms=28_800_000)),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    calm = replace(
        bar(),
        open_time_utc_ms=14_340_000,
        close_time_utc_ms=14_399_999,
        low=Decimal("95"),
        high=Decimal("105"),
    )
    trend = TrendEvidence(
        14_399_999,
        TrendState.NEUTRAL,
        True,
        "d" * 64,
        symbol="BTCUSDT",
    )
    made: list[tuple[object, ...]] = []

    def exit_factory(actual_position, reasons, event_time, _state):
        made.append(reasons)
        return SimpleNamespace(
            intent_id="trend-exit",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            target_execution_time_utc_ms=event_time + 1,
        )

    mmr = replace(maintenance(), effective_end_utc_ms=30_000_000)
    result = process_minute(
        state,
        MinuteInputSlice(
            14_340_000,
            (calm,),
            (calm,),
            (),
            (),
            trend_evidence=(trend,),
        ),
        config(simulation_end_exit_open_utc_ms=28_800_000),
        dependencies(
            exit_intent_factory=exit_factory,
            maintenance_evidence_factory=lambda *_: mmr,
        ),
    )
    assert made[0][0].value == "TREND_EXIT"
    assert result.state.pending_exit_intents[0].intent_id == "trend-exit"
    assert result.planning_outputs[0].intent_id == "trend-exit"


def test_simultaneous_scheduled_reasons_are_preserved_with_intent() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.halt import apply_halt

    pos = replace(
        position(),
        maximum_exit_time_utc_ms=119_999,
        stop_trigger_price=Decimal("80"),
        take_profit_trigger_price=Decimal("120"),
    )
    state = replace(
        apply_halt(
            initial_engine_state(config(simulation_end_exit_open_utc_ms=180_000)),
            0,
            "TEST_HALT",
        ),
        positions=(pos,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )

    def exit_factory(actual_position, reasons, event_time, _state):
        return SimpleNamespace(
            intent_id="multi-reason",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            target_execution_time_utc_ms=event_time + 1,
        )

    result = process_minute(
        state,
        minute(60_000),
        config(simulation_end_exit_open_utc_ms=180_000),
        dependencies(exit_intent_factory=exit_factory),
    )
    assert result.state.pending_exit_reason_matches == (
        (
            "multi-reason",
            (ScheduledExitReason.HALT_EXIT, ScheduledExitReason.TIME_EXIT),
        ),
    )


def test_later_halt_replaces_lower_priority_pending_time_exit() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.halt import apply_halt

    pos = replace(
        position(),
        maximum_exit_time_utc_ms=999_999,
        stop_trigger_price=Decimal("80"),
        take_profit_trigger_price=Decimal("120"),
    )
    old = SimpleNamespace(
        intent_id="time-intent",
        position_id=pos.position_id,
        symbol=pos.symbol,
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
        target_execution_time_utc_ms=180_000,
    )
    state = replace(
        apply_halt(
            initial_engine_state(config(simulation_end_exit_open_utc_ms=240_000)),
            0,
            "TEST_HALT",
        ),
        positions=(pos,),
        pending_exit_intents=(old,),
        pending_exit_reason_matches=(("time-intent", (ScheduledExitReason.TIME_EXIT,)),),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )

    def exit_factory(actual_position, reasons, event_time, _state):
        return SimpleNamespace(
            intent_id="halt-intent",
            position_id=actual_position.position_id,
            symbol=actual_position.symbol,
            scheduled_exit_reason=ScheduledExitReason.HALT_EXIT,
            target_execution_time_utc_ms=event_time + 1,
        )

    result = process_minute(
        state,
        minute(60_000),
        config(simulation_end_exit_open_utc_ms=240_000),
        dependencies(exit_intent_factory=exit_factory),
    )
    assert tuple(item.intent_id for item in result.state.pending_exit_intents) == ("halt-intent",)
    assert result.state.pending_exit_reason_matches == (
        (
            "halt-intent",
            (ScheduledExitReason.HALT_EXIT, ScheduledExitReason.TIME_EXIT),
        ),
    )


def test_exit_account_invariant_failure_is_terminal_invalid() -> None:
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies

    pos = replace(
        position(), stop_trigger_price=Decimal("80"), take_profit_trigger_price=Decimal("120")
    )
    due = SimpleNamespace(
        intent_id="due-exit",
        position_id=pos.position_id,
        symbol=pos.symbol,
        target_execution_time_utc_ms=60_000,
    )
    plan = SimpleNamespace(
        plan_id="exit-plan",
        intent_id="due-exit",
        origin_candidate_id=pos.origin_candidate_id,
        position_id=pos.position_id,
        symbol=pos.symbol,
        position_side=Side.LONG,
        scheduled_exit_reason=ScheduledExitReason.TIME_EXIT,
        target_execution_time_utc_ms=60_000,
        quantity=pos.quantity,
        expected_exit_fill_price=Decimal("1"),
        expected_exit_fee=Decimal("2000"),
    )
    state = replace(
        initial_engine_state(config()),
        wallet_balance=Decimal("1000"),
        equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
        positions=(pos,),
        pending_exit_intents=(due,),
        locked_initial_margin=pos.initial_margin,
        locked_fee_reserve=pos.remaining_fee_reserve,
        locked_funding_reserve=pos.remaining_funding_reserve,
    )
    result = process_minute(
        state,
        minute(60_000),
        config(),
        dependencies(
            planners=PlannerDependencies(None, None, lambda *_: plan, lambda value: value)
        ),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[-1].reason == "EXIT_BATCH_POST_PLAN_INVARIANT_VIOLATION"


def test_funding_record_from_another_minute_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import FundingRecord

    record = FundingRecord(
        "wrong-minute",
        "BTCUSDT",
        120_000,
        Decimal("0.0001"),
        Decimal("100"),
        "a" * 64,
    )
    result = process_minute(
        initial_engine_state(config()),
        replace(minute(), funding_records=(record,)),
        config(),
        dependencies(),
    )
    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[-1].reason == "FUNDING_RECORD_TIME_MISMATCH"


def test_funding_that_breaks_final_account_invariant_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.funding import FundingRecord

    pos = replace(
        position(),
        initial_margin=Decimal("2"),
        isolated_margin_balance=Decimal("2"),
        remaining_fee_reserve=Decimal("3"),
        remaining_funding_reserve=Decimal("10"),
        planned_funding_slice=Decimal("1"),
    )
    state = replace(
        initial_engine_state(config()),
        wallet_balance=Decimal("20"),
        equity=Decimal("20"),
        positions=(pos,),
        locked_initial_margin=Decimal("2"),
        locked_fee_reserve=Decimal("3"),
        locked_funding_reserve=Decimal("10"),
    )
    record = FundingRecord(
        "adverse",
        "BTCUSDT",
        60_000,
        Decimal("0.045"),
        Decimal("100"),
        "a" * 64,
    )
    value = replace(minute(), funding_records=(record,))
    result = process_minute(state, value, config(), dependencies())
    assert result.state.path_state.value == "INVALID"
    assert result.planning_outputs[-1].reason == "ACCOUNT_INVARIANT_VIOLATION"


def test_candidate_intent_is_preserved_in_run_output() -> None:
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs

    candidate = FakeCandidate(candidate_id="candidate", decision_time_utc_ms=0)
    intent = SimpleNamespace(
        intent_id="intent",
        symbol="BTCUSDT",
        target_execution_time_utc_ms=120_000,
    )
    result = run_simulation(
        SimulationInputs((minute(60_000),), (candidate,), ()),
        config(simulation_start_utc_ms=60_000, simulation_end_exit_open_utc_ms=60_000),
        dependencies(entry_intent_factory=lambda _: intent),
    )
    assert result.paths[0].minute_results[0].planning_outputs[0] is intent


def test_canonical_output_writer_is_atomic_and_repeatable(tmp_path) -> None:
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from pa_agent.research_backtest.simulation.output import write_canonical_result

    result = run_simulation(
        SimulationInputs((minute(60_000),), (), ()),
        config(simulation_start_utc_ms=60_000, simulation_end_exit_open_utc_ms=60_000),
        dependencies(),
    )
    first = write_canonical_result(result, tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    second = write_canonical_result(result, tmp_path)
    second_bytes = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    assert first == second
    assert first_bytes == second_bytes
    assert first.simulation_run_id == result.simulation_run_id
    assert first.input_identity_hash == result.simulation_input_identity_hash
    assert first.config_hash == result.config_content_hash
    assert {name for name, _ in first.file_hashes} == {
        "equity.jsonl",
        "events.jsonl",
        "fills.jsonl",
        "ledger.jsonl",
        "path_results.jsonl",
        "planning.jsonl",
        "positions.jsonl",
        "state_snapshots.jsonl",
        "trades.jsonl",
    }
    assert len((tmp_path / "state_snapshots.jsonl").read_text().splitlines()) == 2
    assert not any(path.suffix == ".tmp" for path in tmp_path.iterdir())
