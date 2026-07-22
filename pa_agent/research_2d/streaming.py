from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import pairwise

from pa_agent.research_backtest.domain.rejections import ExecutionRejection
from pa_agent.research_backtest.simulation.context import (
    ProductionRunContext,
    build_production_engine_dependencies,
    validate_production_run_context,
)
from pa_agent.research_backtest.simulation.domain import PathKind, PathState, initial_engine_state
from pa_agent.research_backtest.simulation.engine import (
    MinuteResult,
    build_path_result,
    process_minute,
)
from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice, PathInvalidEvent
from pa_agent.research_backtest.simulation.rejections import (
    RejectionPolicyAction,
    apply_rejection_policy,
)

STREAMING_ADAPTER_VERSION = "RESEARCH_2D_STREAMING_ADAPTER_V2_DRAWDOWN_OBSERVATION"


@dataclass(frozen=True, slots=True)
class StreamPathRun:
    path_kind: PathKind
    state: object
    path_result: object
    events: tuple[object, ...]
    fills: tuple[object, ...]
    ledger_entries: tuple[object, ...]
    trades: tuple[object, ...]
    planning_outputs: tuple[object, ...]
    daily_equity_points: tuple[object, ...]
    engine_peak_observed_drawdown: Decimal
    event_counts: tuple[tuple[str, int], ...]
    processed_minute_count: int
    gap_context: tuple[dict[str, object], ...]


@dataclass(slots=True)
class _Accumulator:
    state: object
    minute_results: list[MinuteResult]
    events: list[object]
    fills: list[object]
    ledgers: list[object]
    trades: list[object]
    planning: list[object]
    daily_equity: list[object]
    engine_peak_observed_drawdown: Decimal
    event_counts: Counter[str]
    gap_context: list[dict[str, object]]
    processed: int = 0
    candidate_cursor: int = 0


def _retain(acc: _Accumulator, result: MinuteResult) -> None:
    acc.state = result.state
    if result.state.peak_equity:
        drawdown = (result.state.peak_equity - result.state.equity) / result.state.peak_equity
        acc.engine_peak_observed_drawdown = max(acc.engine_peak_observed_drawdown, drawdown)
    acc.processed += 1
    acc.fills.extend(result.fills)
    acc.ledgers.extend(result.ledger_entries)
    acc.trades.extend(result.trades)
    acc.planning.extend(result.planning_outputs)
    acc.event_counts.update(getattr(item, "kind", type(item).__name__) for item in result.events)
    time = result.state.final_processed_time_utc_ms
    if result.equity_points and time is not None and (time + 60_000) % 86_400_000 == 0:
        acc.daily_equity.extend(result.equity_points)
    material = bool(
        result.fills or result.trades or result.ledger_entries or result.planning_outputs
    )
    if material or result.state.path_state is not PathState.VALID:
        acc.events.extend(result.events)
    if material or result.state.path_state is not PathState.VALID:
        acc.minute_results.append(result)


def run_streaming_paths(
    context: ProductionRunContext,
    minutes: Iterable[MinuteInputSlice],
    *,
    gap_intervals: tuple[tuple[str, int, int], ...] = (),
    progress_callback: Callable[[int, int], None] | None = None,
    progress_interval_minutes: int = 10_000,
) -> tuple[StreamPathRun, ...]:
    """Run frozen 2C minute economics while retaining only metric-relevant projections."""
    validate_production_run_context(context)
    if any(
        right.decision_time_utc_ms < left.decision_time_utc_ms
        for left, right in pairwise(context.candidates)
    ):
        raise ValueError("streaming Candidate input must be decision-time ordered")
    dependencies = build_production_engine_dependencies(context)
    config = context.config
    accumulators = {
        kind: _Accumulator(
            state=initial_engine_state(config, kind),
            minute_results=[],
            events=[],
            fills=[],
            ledgers=[],
            trades=[],
            planning=[],
            daily_equity=[],
            engine_peak_observed_drawdown=Decimal("0"),
            event_counts=Counter(),
            gap_context=[
                {
                    "symbol": symbol,
                    "start_utc_ms": start,
                    "end_utc_ms": end,
                    "open_position_crosses": False,
                    "due_entry_intent_exists": False,
                    "scheduled_exit_exists": False,
                    "affected_plan_count": 0,
                    "affected_trade_count": 0,
                    "invalid_episode_count": 0,
                }
                for symbol, start, end in gap_intervals
            ],
        )
        for kind in config.active_path_kinds
    }
    expected_time = config.simulation_start_utc_ms
    last_minute: int | None = None
    processed_inputs = 0
    last_reported = 0
    if progress_interval_minutes <= 0:
        raise ValueError("progress interval must be positive")
    for minute in minutes:
        if minute.minute_open_utc_ms != expected_time:
            raise ValueError("streaming inputs must cover contiguous UTC minutes")
        if minute.minute_open_utc_ms > config.simulation_end_exit_open_utc_ms:
            raise ValueError("minute slice lies outside SimulationConfig interval")
        last_minute = minute.minute_open_utc_ms
        processed_inputs += 1
        if progress_callback is not None and (
            processed_inputs == 1 or processed_inputs % progress_interval_minutes == 0
        ):
            progress_callback(processed_inputs, minute.minute_open_utc_ms)
            last_reported = processed_inputs
        expected_time += 60_000
        for acc in accumulators.values():
            state = acc.state
            if state.path_state is PathState.INVALID:
                continue
            active_probes = [
                item
                for item in acc.gap_context
                if item["start_utc_ms"] <= minute.minute_open_utc_ms <= item["end_utc_ms"]
            ]
            for item in active_probes:
                symbol = item["symbol"]
                item["open_position_crosses"] |= any(
                    position.symbol == symbol for position in state.positions
                )
                item["due_entry_intent_exists"] |= any(
                    intent.symbol == symbol
                    and intent.target_execution_time_utc_ms == minute.minute_open_utc_ms
                    for intent in state.pending_entry_intents
                )
                item["scheduled_exit_exists"] |= any(
                    intent.symbol == symbol
                    and intent.target_execution_time_utc_ms == minute.minute_open_utc_ms
                    for intent in state.pending_exit_intents
                )
            cursor = acc.candidate_cursor
            while (
                cursor < len(context.candidates)
                and context.candidates[cursor].decision_time_utc_ms < minute.minute_open_utc_ms
            ):
                cursor += 1
            visible = context.candidates[acc.candidate_cursor : cursor]
            acc.candidate_cursor = cursor
            created: tuple[object, ...] = ()
            if visible:
                created = tuple(dependencies.entry_intent_factory(item) for item in visible)
                rejections = tuple(item for item in created if isinstance(item, ExecutionRejection))
                policy = apply_rejection_policy(rejections, dependencies.stage)
                if policy.action is not RejectionPolicyAction.CONTINUE:
                    invalid = policy.path_invalid_event(minute.minute_open_utc_ms)
                    state = replace(
                        state,
                        path_state=PathState.INVALID,
                        final_processed_time_utc_ms=minute.minute_open_utc_ms,
                    )
                    _retain(acc, MinuteResult(state, (), (), (), (), (), (*created, invalid)))
                    continue
                intents = tuple(
                    item for item in created if hasattr(item, "target_execution_time_utc_ms")
                )
                state = replace(
                    state,
                    pending_entry_intents=tuple(
                        sorted(
                            (*state.pending_entry_intents, *intents),
                            key=lambda item: (item.symbol, item.intent_id),
                        )
                    ),
                    seen_candidate_ids=tuple(
                        sorted(
                            (*state.seen_candidate_ids, *(item.candidate_id for item in visible))
                        )
                    ),
                )
            result = process_minute(state, minute, config, dependencies)
            if created:
                result = replace(result, planning_outputs=(*created, *result.planning_outputs))
            _retain(acc, result)
            for item in active_probes:
                symbol = item["symbol"]
                item["affected_plan_count"] += sum(
                    getattr(output, "symbol", None) == symbol
                    and (
                        hasattr(output, "plan_id")
                        or type(output).__name__.endswith("PlanningOutcome")
                    )
                    for output in result.planning_outputs
                )
                item["affected_trade_count"] += sum(
                    trade.symbol == symbol for trade in result.trades
                )
                if result.state.path_state is PathState.INVALID:
                    item["invalid_episode_count"] += 1
    if last_minute != config.simulation_end_exit_open_utc_ms:
        raise ValueError("streaming inputs do not reach experiment exit open")
    if progress_callback is not None and processed_inputs != last_reported:
        progress_callback(processed_inputs, last_minute)
    output = []
    for kind, acc in accumulators.items():
        state = acc.state
        if state.positions and state.path_state is not PathState.INVALID:
            invalid = PathInvalidEvent(
                config.simulation_end_exit_open_utc_ms, "EXPERIMENT_END_POSITION_OPEN"
            )
            state = replace(
                state,
                path_state=PathState.INVALID,
                final_processed_time_utc_ms=config.simulation_end_exit_open_utc_ms,
            )
            terminal = MinuteResult(state, (), (), (), (), (), (invalid,))
            _retain(acc, terminal)
        path_result = build_path_result(state, acc.minute_results, config.simulation_start_utc_ms)
        output.append(
            StreamPathRun(
                path_kind=kind,
                state=state,
                path_result=path_result,
                events=tuple(acc.events),
                fills=tuple(acc.fills),
                ledger_entries=tuple(acc.ledgers),
                trades=tuple(acc.trades),
                planning_outputs=tuple(acc.planning),
                daily_equity_points=tuple(acc.daily_equity),
                engine_peak_observed_drawdown=acc.engine_peak_observed_drawdown,
                event_counts=tuple(sorted(acc.event_counts.items())),
                processed_minute_count=acc.processed,
                gap_context=tuple(acc.gap_context),
            )
        )
    return tuple(output)
