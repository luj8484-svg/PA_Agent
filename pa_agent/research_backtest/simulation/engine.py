from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import pairwise

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
from pa_agent.research_backtest.simulation.ambiguity import resolve_ambiguity
from pa_agent.research_backtest.simulation.domain import (
    EngineState,
    PathKind,
    PathState,
    SimulationConfig,
    initial_engine_state,
)
from pa_agent.research_backtest.simulation.fills import (
    FillEvent,
    TradeRecord,
    apply_entry_fill,
    apply_exit_fill,
    make_entry_fill,
    make_protective_exit_fill,
    make_scheduled_exit_fill,
    stable_entry_plan_order,
)
from pa_agent.research_backtest.simulation.funding import (
    FundingRecord,
    FundingReserveExceeded,
    apply_funding_to_position,
    settle_funding,
)
from pa_agent.research_backtest.simulation.halt import apply_halt, drawdown_breached
from pa_agent.research_backtest.simulation.inputs import (
    MinuteBar,
    MinuteInputSlice,
    PathInvalidEvent,
    SimulationInputs,
    validate_minute_inputs,
)
from pa_agent.research_backtest.simulation.ledger import (
    AccountInvariantError,
    LedgerEntry,
    LedgerKind,
    available_balance,
    mark_equity,
    reduce_ledger,
)
from pa_agent.research_backtest.simulation.liquidation import (
    estimated_liquidation,
)
from pa_agent.research_backtest.simulation.output import PathResult
from pa_agent.research_backtest.simulation.planning import (
    EntryBatchPostPlanInvariantError,
    PlannerDependencies,
    choose_scheduled_reason,
    merge_scheduled_reasons,
    plan_due_entry_batch,
    plan_due_exits,
    scheduled_exit_reasons,
    validate_entry_batch_post_plan,
)
from pa_agent.research_backtest.simulation.positions import (
    IsolatedPosition,
    position_from_entry_plan,
)
from pa_agent.research_backtest.simulation.triggers import (
    TriggerCandidate,
    choose_open_gap_trigger,
    discover_intraminute_candidates,
    discover_open_gap_candidates,
)
from pa_agent.research_backtest.simulation.versions import EVENT_STAGES


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    event_id: str
    event_time_utc_ms: int
    path_kind: PathKind
    stage: str
    kind: str
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class EquityPoint:
    event_time_utc_ms: int
    path_kind: PathKind
    wallet_balance: Decimal
    locked_initial_margin: Decimal
    locked_fee_reserve: Decimal
    locked_funding_reserve: Decimal
    available_balance: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    peak_equity: Decimal
    drawdown: Decimal
    path_state: PathState


@dataclass(frozen=True, slots=True)
class EngineDependencies:
    planners: PlannerDependencies
    entry_intent_factory: Callable[[object], object] | None
    exit_intent_factory: (
        Callable[[IsolatedPosition, tuple[object, ...], int, EngineState], object] | None
    )
    planning_evidence_factory: Callable[[EngineState, MinuteInputSlice], object]
    maintenance_evidence_factory: Callable[[IsolatedPosition, int], object]
    execution_cost_factory: Callable[[str, int], object]
    exit_delay_minutes: int | None = None

    def __post_init__(self) -> None:
        configured = self.exit_delay_minutes
        factory_delay = getattr(self.exit_intent_factory, "exit_delay_minutes", None)
        for value in (configured, factory_delay):
            if value is not None and (type(value) is not int or value not in {0, 1, 2}):
                raise ValueError("exit delay must be 0, 1, or 2 minutes")
        if configured is not None and factory_delay is not None and configured != factory_delay:
            raise ValueError("EngineDependencies exit delay does not match intent factory")

    @property
    def resolved_exit_delay_minutes(self) -> int:
        factory_delay = getattr(self.exit_intent_factory, "exit_delay_minutes", None)
        value = factory_delay if factory_delay is not None else self.exit_delay_minutes
        if value is None:
            return 0
        if type(value) is not int or value not in {0, 1, 2}:
            raise ValueError("exit delay must be 0, 1, or 2 minutes")
        return value


@dataclass(frozen=True, slots=True)
class MinuteResult:
    state: EngineState
    events: tuple[SimulationEvent, ...]
    fills: tuple[FillEvent, ...]
    ledger_entries: tuple[LedgerEntry, ...]
    trades: tuple[TradeRecord, ...]
    equity_points: tuple[EquityPoint, ...]
    planning_outputs: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class PathRun:
    path_kind: PathKind
    minute_results: tuple[MinuteResult, ...]
    path_result: PathResult


@dataclass(frozen=True, slots=True)
class SimulationResult:
    config_id: str
    config_content_hash: str
    paths: tuple[PathRun, ...]


def _event(state: EngineState, time: int, stage: str, kind: str, subject: str | None = None):
    payload = {
        "event_time_utc_ms": time,
        "path_kind": state.path_kind,
        "stage": stage,
        "kind": kind,
        "subject_id": subject,
    }
    return SimulationEvent(
        "event_" + canonical_sha256(payload)[:24],
        time,
        state.path_kind,
        stage,
        kind,
        subject,
    )


def _bar(bars: tuple[MinuteBar, ...], symbol: str) -> MinuteBar:
    try:
        return next(item for item in bars if item.symbol == symbol)
    except StopIteration as exc:
        raise ValueError(f"missing {symbol} bar") from exc


def _unrealized(position: IsolatedPosition, mark: Decimal) -> Decimal:
    if position.side is Side.LONG:
        return position.quantity * (mark - position.entry_price)
    return position.quantity * (position.entry_price - mark)


def _mark_total(positions: tuple[object, ...], bars: tuple[MinuteBar, ...], field: str) -> Decimal:
    total = Decimal("0")
    for item in positions:
        mark = getattr(_bar(bars, item.symbol), field)
        total += _unrealized(item, mark)
    return total


def _equity_point(state: EngineState, time: int) -> EquityPoint:
    drawdown = (
        (state.peak_equity - state.equity) / state.peak_equity
        if state.peak_equity > 0
        else Decimal("0")
    )
    return EquityPoint(
        time,
        state.path_kind,
        state.wallet_balance,
        state.locked_initial_margin,
        state.locked_fee_reserve,
        state.locked_funding_reserve,
        available_balance(state),
        state.unrealized_pnl,
        state.equity,
        state.peak_equity,
        drawdown,
        state.path_state,
    )


def _invalid_result(
    state: EngineState,
    reason: str,
    time: int,
    events: list[SimulationEvent],
    fills: list[FillEvent],
    ledgers: list[LedgerEntry],
    trades: list[TradeRecord],
    planning: list[object],
) -> MinuteResult:
    invalid = replace(
        state,
        path_state=PathState.INVALID,
        final_processed_time_utc_ms=time,
    )
    planning.append(PathInvalidEvent(time, reason))
    return MinuteResult(
        invalid,
        tuple(events),
        tuple(fills),
        tuple(ledgers),
        tuple(trades),
        (),
        tuple(planning),
    )


def _funding_entries(
    state: EngineState, position: IsolatedPosition, record: FundingRecord, settlement: object
) -> tuple[LedgerEntry, LedgerEntry]:
    obligation = settlement.obligation_id
    return (
        LedgerEntry(
            f"{obligation}:wallet",
            record.funding_time_utc_ms,
            LedgerKind.FUNDING,
            settlement.wallet_delta,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        ),
        LedgerEntry(
            f"{obligation}:reserve",
            record.funding_time_utc_ms,
            LedgerKind.FUNDING_RESERVE_RELEASE,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            -settlement.reserve_release,
            Decimal("0"),
        ),
    )


def process_minute(
    state: EngineState,
    minute: MinuteInputSlice,
    config: SimulationConfig,
    dependencies: EngineDependencies,
) -> MinuteResult:
    time = minute.minute_open_utc_ms
    events: list[SimulationEvent] = []
    fills: list[FillEvent] = []
    ledgers: list[LedgerEntry] = []
    trades: list[TradeRecord] = []
    planning: list[object] = []

    events.append(_event(state, time, EVENT_STAGES[0], "STAGE"))
    events.append(_event(state, time, EVENT_STAGES[1], "STAGE"))
    intents_due_now = tuple(
        item
        for item in (*state.pending_entry_intents, *state.pending_exit_intents)
        if item.target_execution_time_utc_ms == time
    )
    validated = validate_minute_inputs(
        has_positions=bool(state.positions),
        has_due_event=bool(intents_due_now),
        minute=minute,
        held_symbols=tuple(sorted(item.symbol for item in state.positions)),
        due_symbols=tuple(sorted({item.symbol for item in intents_due_now})),
        trend_evidence_expected_symbols=(
            tuple(sorted(item.symbol for item in state.positions))
            if (time + 60_000) % 14_400_000 == 0
            else ()
        ),
    )
    if isinstance(validated, PathInvalidEvent):
        return _invalid_result(
            state, validated.reason, time, events, fills, ledgers, trades, planning
        )

    events.append(_event(state, time, EVENT_STAGES[2], "STAGE"))
    if dependencies.exit_intent_factory is not None:
        pending_positions = {
            getattr(intent, "position_id", None) for intent in state.pending_exit_intents
        }
        time_exit_intents: list[object] = []
        time_exit_matches: list[tuple[str, tuple[object, ...]]] = []
        for pos in state.positions:
            if pos.position_id in pending_positions or time != pos.maximum_exit_time_utc_ms:
                continue
            reasons = (ScheduledExitReason.TIME_EXIT,)
            intent = dependencies.exit_intent_factory(pos, reasons, time, state)
            time_exit_intents.append(intent)
            time_exit_matches.append((intent.intent_id, reasons))
        if time_exit_intents:
            planning.extend(time_exit_intents)
            state = replace(
                state,
                pending_exit_intents=tuple(
                    sorted(
                        (*state.pending_exit_intents, *time_exit_intents),
                        key=lambda item: (item.symbol, item.intent_id),
                    )
                ),
                pending_exit_reason_matches=tuple(
                    sorted((*state.pending_exit_reason_matches, *time_exit_matches))
                ),
            )
    events.append(_event(state, time, EVENT_STAGES[3], "STAGE"))
    for record in minute.funding_records:
        for pos in tuple(state.positions):
            obligation_id = f"{pos.position_id}:{record.record_id}"
            if pos.symbol != record.symbol or obligation_id in state.consumed_funding_ids:
                continue
            settlement = settle_funding(pos, record)
            if isinstance(settlement, FundingReserveExceeded):
                planning.append(settlement)
                return _invalid_result(
                    state, settlement.reason, time, events, fills, ledgers, trades, planning
                )
            entries = _funding_entries(state, pos, record, settlement)
            try:
                state = reduce_ledger(state, entries)
            except AccountInvariantError:
                return _invalid_result(
                    state,
                    "ACCOUNT_INVARIANT_VIOLATION",
                    time,
                    events,
                    fills,
                    ledgers,
                    trades,
                    planning,
                )
            updated = apply_funding_to_position(pos, settlement)
            state = replace(
                state,
                positions=tuple(
                    updated if item.position_id == pos.position_id else item
                    for item in state.positions
                ),
                consumed_funding_ids=tuple(sorted((*state.consumed_funding_ids, obligation_id))),
            )
            ledgers.extend(entries)
            events.append(_event(state, time, EVENT_STAGES[3], "FUNDING", record.record_id))

    events.append(_event(state, time, EVENT_STAGES[4], "STAGE"))
    for pos in tuple(state.positions):
        evidence = dependencies.maintenance_evidence_factory(pos, time)
        reference = estimated_liquidation(pos, evidence, time)
        if isinstance(reference, PathInvalidEvent):
            return _invalid_result(
                state, reference.reason, time, events, fills, ledgers, trades, planning
            )
        trade_bar = _bar(minute.trade_bars, pos.symbol)
        mark_bar = _bar(minute.mark_bars, pos.symbol)
        candidates = discover_open_gap_candidates(
            pos, trade_bar, mark_bar, reference.liquidation_price
        )
        if not candidates:
            continue
        chosen = choose_open_gap_trigger(candidates)
        cost = dependencies.execution_cost_factory(pos.symbol, time)
        fill = make_protective_exit_fill(
            pos,
            chosen,
            time,
            slippage_rate=cost.slippage_rate,
            fee_rate=cost.fee_rate,
            tick_size=cost.tick_size,
        )
        try:
            state, entries, trade = apply_exit_fill(state, pos, fill)
        except AccountInvariantError:
            return _invalid_result(
                state,
                "ACCOUNT_INVARIANT_VIOLATION",
                time,
                events,
                fills,
                ledgers,
                trades,
                planning,
            )
        fills.append(fill)
        ledgers.extend(entries)
        trades.append(trade)
        events.append(_event(state, time, EVENT_STAGES[4], "PROTECTIVE_EXIT", pos.position_id))
        cancelled = tuple(
            intent
            for intent in state.pending_exit_intents
            if getattr(intent, "position_id", None) == pos.position_id
        )
        if cancelled:
            for intent in cancelled:
                events.append(
                    _event(
                        state,
                        time,
                        EVENT_STAGES[4],
                        "SCHEDULED_EXIT_CANCELLED",
                        intent.intent_id,
                    )
                )
            state = replace(
                state,
                pending_exit_intents=tuple(
                    intent for intent in state.pending_exit_intents if intent not in cancelled
                ),
                pending_exit_reason_matches=tuple(
                    item
                    for item in state.pending_exit_reason_matches
                    if item[0] not in {intent.intent_id for intent in cancelled}
                ),
            )

    events.append(_event(state, time, EVENT_STAGES[5], "STAGE"))
    due_exits = tuple(
        intent
        for intent in state.pending_exit_intents
        if intent.target_execution_time_utc_ms == time
        if any(pos.position_id == getattr(intent, "position_id", None) for pos in state.positions)
    )
    if due_exits:
        evidence = dependencies.planning_evidence_factory(state, minute)
        outputs = plan_due_exits(state, due_exits, time, evidence, dependencies.planners)
        planning.extend(outputs)
        for output in outputs:
            if not hasattr(output, "expected_exit_fill_price"):
                rejection_reason = getattr(output, "reason", "UNKNOWN")
                rejection_code = getattr(rejection_reason, "value", str(rejection_reason))
                return _invalid_result(
                    state,
                    f"SCHEDULED_EXIT_PLANNING_REJECTED:{rejection_code}",
                    time,
                    events,
                    fills,
                    ledgers,
                    trades,
                    planning,
                )
            pos = next(
                (item for item in state.positions if item.position_id == output.position_id), None
            )
            if pos is None:
                continue
            reason = output.scheduled_exit_reason
            matched = dict(state.pending_exit_reason_matches).get(output.intent_id, (reason,))
            fill = make_scheduled_exit_fill(output, matched, reason)
            try:
                state, entries, trade = apply_exit_fill(state, pos, fill)
            except AccountInvariantError:
                return _invalid_result(
                    state,
                    "ACCOUNT_INVARIANT_VIOLATION",
                    time,
                    events,
                    fills,
                    ledgers,
                    trades,
                    planning,
                )
            fills.append(fill)
            ledgers.extend(entries)
            trades.append(trade)
        due_ids = {intent.intent_id for intent in due_exits}
        state = replace(
            state,
            pending_exit_intents=tuple(
                intent for intent in state.pending_exit_intents if intent.intent_id not in due_ids
            ),
            pending_exit_reason_matches=tuple(
                item for item in state.pending_exit_reason_matches if item[0] not in due_ids
            ),
        )

    events.append(_event(state, time, EVENT_STAGES[6], "STAGE"))
    open_unrealized = _mark_total(state.positions, minute.mark_bars, "open")
    state = mark_equity(state, open_unrealized)
    if state.path_state is PathState.VALID and drawdown_breached(state.peak_equity, state.equity):
        state = apply_halt(state, time, "OPEN_EQUITY_DRAWDOWN_10_PERCENT")

    events.append(_event(state, time, EVENT_STAGES[7], "STAGE"))
    due_entries = tuple(
        intent
        for intent in state.pending_entry_intents
        if intent.target_execution_time_utc_ms == time
    )
    if due_entries and (
        state.path_state is PathState.HALTED or time >= config.simulation_end_exit_open_utc_ms
    ):
        kind = (
            "EXPERIMENT_END_ENTRY_CANCELLED"
            if time >= config.simulation_end_exit_open_utc_ms
            else "HALTED_ENTRY_CANCELLED"
        )
        for intent in due_entries:
            events.append(_event(state, time, EVENT_STAGES[7], kind, intent.intent_id))
        due_ids = {item.intent_id for item in due_entries}
        state = replace(
            state,
            pending_entry_intents=tuple(
                item for item in state.pending_entry_intents if item.intent_id not in due_ids
            ),
        )
        due_entries = ()
    if due_entries:
        evidence = dependencies.planning_evidence_factory(state, minute)
        outcome = plan_due_entry_batch(state, due_entries, time, evidence, dependencies.planners)
        if outcome is None:
            raise AssertionError("due entry batch produced no planning outcome")
        planning.extend(outcome.audit_objects)
        try:
            validate_entry_batch_post_plan(outcome, available_balance=available_balance(state))
        except EntryBatchPostPlanInvariantError:
            return _invalid_result(
                state,
                "ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION",
                time,
                events,
                fills,
                ledgers,
                trades,
                planning,
            )
        plans = stable_entry_plan_order(outcome.plans)
        for plan in plans:
            fill = make_entry_fill(plan)
            pos = position_from_entry_plan(plan)
            state, entries = apply_entry_fill(state, fill, pos)
            fills.append(fill)
            ledgers.extend(entries)
        due_ids = {item.intent_id for item in due_entries}
        state = replace(
            state,
            pending_entry_intents=tuple(
                item for item in state.pending_entry_intents if item.intent_id not in due_ids
            ),
        )

    events.append(_event(state, time, EVENT_STAGES[8], "STAGE"))
    events.append(_event(state, time, EVENT_STAGES[9], "STAGE"))
    intraminute_exposure = tuple(state.positions)
    opening_wallet = state.wallet_balance
    trigger_map: list[tuple[IsolatedPosition, tuple[TriggerCandidate, ...], object]] = []
    for pos in tuple(state.positions):
        evidence = dependencies.maintenance_evidence_factory(pos, time)
        reference = estimated_liquidation(pos, evidence, time)
        if isinstance(reference, PathInvalidEvent):
            return _invalid_result(
                state, reference.reason, time, events, fills, ledgers, trades, planning
            )
        candidates = discover_intraminute_candidates(
            pos,
            _bar(minute.trade_bars, pos.symbol),
            _bar(minute.mark_bars, pos.symbol),
            reference.liquidation_price,
        )
        cost = dependencies.execution_cost_factory(pos.symbol, time)
        enriched: list[TriggerCandidate] = []
        for item in candidates:
            probe = make_protective_exit_fill(
                pos,
                item,
                time,
                slippage_rate=cost.slippage_rate,
                fee_rate=cost.fee_rate,
                tick_size=cost.tick_size,
            )
            gross = (
                pos.quantity * (probe.fill_price - pos.entry_price)
                if pos.side is Side.LONG
                else pos.quantity * (pos.entry_price - probe.fill_price)
            )
            enriched.append(
                replace(item, minute_end_equity=state.wallet_balance + gross - probe.fee)
            )
        trigger_map.append((pos, tuple(enriched), cost))

    events.append(_event(state, time, EVENT_STAGES[10], "STAGE"))
    selected: list[tuple[IsolatedPosition, TriggerCandidate, object]] = []
    for pos, candidates, cost in trigger_map:
        if not candidates:
            continue
        chosen = (
            candidates[0]
            if len(candidates) == 1
            else resolve_ambiguity(state.path_kind, state, candidates)
        )
        if len(candidates) > 1:
            events.append(_event(state, time, EVENT_STAGES[10], "PATH_AMBIGUOUS", pos.position_id))
        selected.append((pos, chosen, cost))

    events.append(_event(state, time, EVENT_STAGES[11], "STAGE"))
    for pos, chosen, cost in selected:
        if not any(item.position_id == pos.position_id for item in state.positions):
            continue
        fill = make_protective_exit_fill(
            pos,
            chosen,
            time,
            slippage_rate=cost.slippage_rate,
            fee_rate=cost.fee_rate,
            tick_size=cost.tick_size,
        )
        try:
            state, entries, trade = apply_exit_fill(state, pos, fill)
        except AccountInvariantError:
            return _invalid_result(
                state,
                "ACCOUNT_INVARIANT_VIOLATION",
                time,
                events,
                fills,
                ledgers,
                trades,
                planning,
            )
        fills.append(fill)
        ledgers.extend(entries)
        trades.append(trade)
        cancelled = tuple(
            intent
            for intent in state.pending_exit_intents
            if getattr(intent, "position_id", None) == pos.position_id
        )
        if cancelled:
            cancelled_ids = {intent.intent_id for intent in cancelled}
            for intent in cancelled:
                events.append(
                    _event(
                        state,
                        time,
                        EVENT_STAGES[11],
                        "SCHEDULED_EXIT_CANCELLED",
                        intent.intent_id,
                    )
                )
            state = replace(
                state,
                pending_exit_intents=tuple(
                    intent
                    for intent in state.pending_exit_intents
                    if intent.intent_id not in cancelled_ids
                ),
                pending_exit_reason_matches=tuple(
                    item
                    for item in state.pending_exit_reason_matches
                    if item[0] not in cancelled_ids
                ),
            )

    events.append(_event(state, time, EVENT_STAGES[12], "STAGE"))
    close_unrealized = _mark_total(state.positions, minute.mark_bars, "close")
    state = mark_equity(state, close_unrealized)

    events.append(_event(state, time, EVENT_STAGES[13], "STAGE"))
    if intraminute_exposure:
        worst = opening_wallet
        for pos in intraminute_exposure:
            mark_bar = _bar(minute.mark_bars, pos.symbol)
            adverse = mark_bar.low if pos.side is Side.LONG else mark_bar.high
            worst += _unrealized(pos, adverse)
        if state.path_state is PathState.VALID and drawdown_breached(state.peak_equity, worst):
            state = apply_halt(state, time, "INTRAMINUTE_DRAWDOWN_10_PERCENT")
    if state.path_state is PathState.VALID and drawdown_breached(state.peak_equity, state.equity):
        state = apply_halt(state, time, "CLOSE_DRAWDOWN_10_PERCENT")

    close_time = time + 59_999
    if dependencies.exit_intent_factory is not None:
        pending_intents = list(state.pending_exit_intents)
        reason_matches = dict(state.pending_exit_reason_matches)
        created_intents: list[object] = []
        for pos in state.positions:
            existing = next(
                (
                    intent
                    for intent in pending_intents
                    if getattr(intent, "position_id", None) == pos.position_id
                ),
                None,
            )
            trend = next(
                (
                    item
                    for item in minute.trend_evidence
                    if item.symbol == pos.symbol and item.decision_time_utc_ms == close_time
                ),
                None,
            )
            reasons = scheduled_exit_reasons(
                pos,
                close_time,
                trend,
                state.path_state is PathState.HALTED,
                config.simulation_end_exit_open_utc_ms,
                dependencies.resolved_exit_delay_minutes,
            )
            if not reasons:
                continue
            existing_reasons = (
                reason_matches.get(existing.intent_id, ()) if existing is not None else ()
            )
            if existing is not None and not existing_reasons:
                existing_reason = getattr(existing, "scheduled_exit_reason", None)
                existing_reasons = (existing_reason,) if existing_reason is not None else ()
            combined = merge_scheduled_reasons(existing_reasons, reasons)
            selected = choose_scheduled_reason(combined)
            if (
                existing is not None
                and getattr(existing, "scheduled_exit_reason", None) is selected
            ):
                reason_matches[existing.intent_id] = combined
                continue
            if existing is not None:
                pending_intents.remove(existing)
                reason_matches.pop(existing.intent_id, None)
                events.append(
                    _event(
                        state,
                        time,
                        EVENT_STAGES[13],
                        "SCHEDULED_EXIT_SUPERSEDED",
                        existing.intent_id,
                    )
                )
            intent = dependencies.exit_intent_factory(pos, combined, close_time, state)
            pending_intents.append(intent)
            reason_matches[intent.intent_id] = combined
            created_intents.append(intent)
        planning.extend(created_intents)
        state = replace(
            state,
            pending_exit_intents=tuple(
                sorted(
                    pending_intents,
                    key=lambda item: (item.symbol, item.intent_id),
                )
            ),
            pending_exit_reason_matches=tuple(sorted(reason_matches.items())),
        )
    flat_time = state.flat_after_halt_time_utc_ms
    if state.path_state is PathState.HALTED and not state.positions and flat_time is None:
        flat_time = time
    state = replace(
        state,
        final_processed_time_utc_ms=time,
        flat_after_halt_time_utc_ms=flat_time,
    )
    return MinuteResult(
        state,
        tuple(events),
        tuple(fills),
        tuple(ledgers),
        tuple(trades),
        (_equity_point(state, time),),
        tuple(planning),
    )


def run_simulation(
    inputs: SimulationInputs,
    config: SimulationConfig,
    dependencies: EngineDependencies,
) -> SimulationResult:
    minute_opens = tuple(item.minute_open_utc_ms for item in inputs.minute_slices)
    if (
        not minute_opens
        or minute_opens[0] != config.simulation_start_utc_ms
        or minute_opens[-1] != config.simulation_end_exit_open_utc_ms
        or any(right - left != 60_000 for left, right in pairwise(minute_opens))
    ):
        raise ValueError(
            "simulation inputs must cover contiguous UTC minutes from start through exit open"
        )
    paths: list[PathRun] = []
    for path_kind in config.active_path_kinds:
        state = initial_engine_state(config, path_kind)
        minute_results: list[MinuteResult] = []
        for minute in inputs.minute_slices:
            if not (
                config.simulation_start_utc_ms
                <= minute.minute_open_utc_ms
                <= config.simulation_end_exit_open_utc_ms
            ):
                raise ValueError("minute slice lies outside SimulationConfig interval")
            visible = tuple(
                candidate
                for candidate in inputs.candidates
                if candidate.decision_time_utc_ms < minute.minute_open_utc_ms
                and candidate.candidate_id not in state.seen_candidate_ids
            )
            if visible:
                if dependencies.entry_intent_factory is None:
                    raise ValueError("Candidate stream requires an EntryIntent factory")
                created = tuple(dependencies.entry_intent_factory(item) for item in visible)
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
            if visible:
                result = replace(
                    result,
                    planning_outputs=(*created, *result.planning_outputs),
                )
            minute_results.append(result)
            state = result.state
            if state.path_state is PathState.INVALID:
                break
        if state.positions and state.path_state is not PathState.INVALID:
            invalid_event = PathInvalidEvent(
                config.simulation_end_exit_open_utc_ms,
                "EXPERIMENT_END_POSITION_OPEN",
            )
            state = replace(
                state,
                path_state=PathState.INVALID,
                final_processed_time_utc_ms=config.simulation_end_exit_open_utc_ms,
            )
            terminal = minute_results[-1]
            minute_results[-1] = replace(
                terminal,
                state=state,
                equity_points=(),
                planning_outputs=(*terminal.planning_outputs, invalid_event),
            )
        path_result = PathResult(
            path_state=state.path_state,
            final_processed_time_utc_ms=state.final_processed_time_utc_ms
            if state.final_processed_time_utc_ms is not None
            else config.simulation_start_utc_ms,
            invalid_reason=(
                next(
                    (
                        item.reason
                        for result in reversed(minute_results)
                        for item in result.planning_outputs
                        if isinstance(item, PathInvalidEvent)
                    ),
                    None,
                )
            ),
            halt_trigger_time_utc_ms=state.halt_trigger_time_utc_ms,
            halt_reason=state.halt_reason,
            entry_disabled=state.path_state is PathState.HALTED,
            flat_after_halt_time_utc_ms=state.flat_after_halt_time_utc_ms,
        )
        paths.append(PathRun(path_kind, tuple(minute_results), path_result))
    if len(paths) > 2:
        raise AssertionError("active simulation path count exceeded two")
    return SimulationResult(config.config_id, config.config_content_hash, tuple(paths))
