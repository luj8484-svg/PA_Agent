from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side, TrendState


@dataclass(frozen=True)
class FakeIntent:
    intent_id: str
    target_execution_time_utc_ms: int
    symbol: str = "BTCUSDT"


def test_entry_planner_receives_target_minute_current_state() -> None:
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies, plan_due_entries

    calls: list[object] = []
    state = object()
    evidence = object()

    def factory(actual_state, intent, actual_evidence):
        calls.append((actual_state, intent, actual_evidence))
        return ("inputs", actual_state)

    deps = PlannerDependencies(factory, lambda inputs: ("plan", inputs), None, None)
    result = plan_due_entries(
        state, (FakeIntent("i2", 60_000), FakeIntent("i1", 60_000)), 60_000, evidence, deps
    )
    assert [call[1].intent_id for call in calls] == ["i1", "i2"]
    assert all(call[0] is state and call[2] is evidence for call in calls)
    assert result[0][0] == "plan"


def test_future_entry_intent_is_not_planned() -> None:
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies, plan_due_entries

    deps = PlannerDependencies(
        lambda *_: pytest.fail("future intent used"), lambda x: x, None, None
    )
    assert (
        plan_due_entries(object(), (FakeIntent("future", 120_000),), 60_000, object(), deps) == ()
    )


def test_funding_and_exit_state_changes_are_visible_to_entry_planner() -> None:
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies, plan_due_entries

    @dataclass(frozen=True)
    class State:
        wallet_balance: Decimal

    observed: list[Decimal] = []
    deps = PlannerDependencies(
        lambda current, *_: observed.append(current.wallet_balance) or current,
        lambda current: current,
        None,
        None,
    )
    post_funding_and_exit = State(Decimal("9750"))
    plan_due_entries(
        post_funding_and_exit,
        (FakeIntent("due", 60_000),),
        60_000,
        object(),
        deps,
    )
    assert observed == [Decimal("9750")]


def test_exit_planner_receives_current_position_snapshot() -> None:
    from pa_agent.research_backtest.simulation.planning import PlannerDependencies, plan_due_exits

    seen: list[object] = []
    deps = PlannerDependencies(
        None,
        None,
        lambda state, intent, evidence: seen.append((state, intent, evidence)) or intent,
        lambda value: ("exit-plan", value.intent_id),
    )
    result = plan_due_exits(object(), (FakeIntent("exit", 60_000),), 60_000, object(), deps)
    assert result == (("exit-plan", "exit"),)
    assert len(seen) == 1


def test_complete_run_input_has_no_prefabricated_plan_stream() -> None:
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs

    with pytest.raises(TypeError):
        SimulationInputs(
            minute_slices=(),
            candidates=(),
            evidence_hashes=(),
            entry_plans=(),
        )


def pos():
    from pa_agent.research_backtest.simulation.positions import IsolatedPosition

    return IsolatedPosition(
        "p",
        "BTCUSDT",
        Side.LONG,
        Decimal("1"),
        0,
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("90"),
        Decimal("120"),
        Decimal("1"),
        Decimal("2"),
        Decimal("1"),
        2,
        "plan",
        "candidate",
        120_000,
    )


def test_time_exit_only_at_origin_plan_maximum() -> None:
    from pa_agent.research_backtest.simulation.planning import scheduled_exit_reasons

    assert scheduled_exit_reasons(pos(), 119_999, None, False, 600_000) == ()
    assert scheduled_exit_reasons(pos(), 120_000, None, False, 600_000) == (
        ScheduledExitReason.TIME_EXIT,
    )


def test_trend_exit_requires_closed_evidence_and_loss_of_direction() -> None:
    from pa_agent.research_backtest.simulation.planning import TrendEvidence, scheduled_exit_reasons

    bull = TrendEvidence(119_999, TrendState.BULL, True, "a" * 64)
    neutral = replace(bull, trend_state=TrendState.NEUTRAL)
    unclosed = replace(neutral, is_closed=False)
    assert scheduled_exit_reasons(pos(), 119_999, bull, False, 600_000) == ()
    assert scheduled_exit_reasons(pos(), 119_999, neutral, False, 600_000) == (
        ScheduledExitReason.TREND_EXIT,
    )
    with pytest.raises(ValueError, match="closed"):
        scheduled_exit_reasons(pos(), 119_999, unclosed, False, 600_000)


def test_short_trend_exit_is_symmetric() -> None:
    from pa_agent.research_backtest.simulation.planning import TrendEvidence, scheduled_exit_reasons

    short = replace(pos(), side=Side.SHORT)
    bear = TrendEvidence(119_999, TrendState.BEAR, True, "a" * 64)
    bull = replace(bear, trend_state=TrendState.BULL)
    assert scheduled_exit_reasons(short, 119_999, bear, False, 600_000) == ()
    assert scheduled_exit_reasons(short, 119_999, bull, False, 600_000) == (
        ScheduledExitReason.TREND_EXIT,
    )


def test_scheduled_exit_reason_priority_is_closed() -> None:
    from pa_agent.research_backtest.simulation.planning import choose_scheduled_reason

    all_reasons = tuple(ScheduledExitReason)
    assert choose_scheduled_reason(all_reasons) is ScheduledExitReason.HALT_EXIT
    assert (
        choose_scheduled_reason((ScheduledExitReason.TIME_EXIT, ScheduledExitReason.TREND_EXIT))
        is ScheduledExitReason.TREND_EXIT
    )


def test_experiment_end_condition_occurs_before_target_open() -> None:
    from pa_agent.research_backtest.simulation.planning import experiment_end_condition_time

    assert experiment_end_condition_time(600_000) == 599_999


def test_missing_expected_trend_evidence_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
    from pa_agent.research_backtest.simulation.planning import discover_scheduled_exits

    result = discover_scheduled_exits(
        pos(),
        event_time_utc_ms=14_399_999,
        trend_evidence=None,
        trend_evidence_expected=True,
        halted=False,
        simulation_end_exit_open_utc_ms=99_999_999,
    )
    assert isinstance(result, PathInvalidEvent)
    assert result.reason == "TREND_EVIDENCE_UNAVAILABLE"


def test_production_candidate_factory_calls_existing_2b_intent_function() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.domain.enums import ResearchStage
    from pa_agent.research_backtest.domain.intents import EntryIntent
    from pa_agent.research_backtest.simulation.planning import make_candidate_intent_factory
    from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs

    candidate = complete_entry_inputs().candidate
    factory = make_candidate_intent_factory(
        execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
        computational_experiment_id="f" * 64,
        stage=ResearchStage.BACKTEST,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    assert isinstance(factory(candidate), EntryIntent)


def test_production_exit_factory_calls_existing_2b_intent_function() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.domain.enums import ScheduledExitReason
    from pa_agent.research_backtest.domain.intents import ExitIntent
    from pa_agent.research_backtest.simulation.planning import make_scheduled_exit_intent_factory

    factory = make_scheduled_exit_intent_factory(
        execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
        computational_experiment_id="e" * 64,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    result = factory(
        pos(),
        (ScheduledExitReason.TREND_EXIT, ScheduledExitReason.TIME_EXIT),
        119_999,
        object(),
    )
    assert isinstance(result, ExitIntent)
    assert result.scheduled_exit_reason is ScheduledExitReason.TREND_EXIT
    assert result.target_execution_time_utc_ms == 180_000
