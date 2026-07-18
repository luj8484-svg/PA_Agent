from dataclasses import replace
from decimal import Decimal

from pa_agent.research_backtest.domain.enums import ResearchStage, ScheduledExitReason
from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs


def _position():
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan

    plan = build_entry_batch_planning_outcome(_batch_inputs()).plans[0]
    return position_from_entry_plan(plan)


def test_exit_execution_projection_ignores_funding_but_detects_geometry_change() -> None:
    from pa_agent.research_backtest.simulation.positions import (
        exit_execution_position_snapshot,
    )

    position = _position()
    funded = replace(
        position,
        remaining_funding_reserve=position.remaining_funding_reserve / Decimal("2"),
        remaining_funding_events=max(0, position.remaining_funding_events - 1),
        funding_wallet_delta_sum=Decimal("-1.25"),
    )
    resized = replace(position, quantity=position.quantity / Decimal("2"))

    assert exit_execution_position_snapshot(funded) == exit_execution_position_snapshot(position)
    assert (
        exit_execution_position_snapshot(resized).snapshot_content_hash
        != exit_execution_position_snapshot(position).snapshot_content_hash
    )


def test_scheduled_exit_condition_freezes_execution_projection_hash() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.planning import (
        make_scheduled_exit_intent_factory,
    )
    from pa_agent.research_backtest.simulation.positions import (
        exit_execution_position_snapshot,
    )

    position = _position()
    factory = make_scheduled_exit_intent_factory(
        execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
        computational_experiment_id="e" * 64,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    intent = factory(
        position,
        (ScheduledExitReason.TIME_EXIT,),
        20_000_123,
        object(),
    )
    assert (
        intent.position_snapshot_hash
        == exit_execution_position_snapshot(position).snapshot_content_hash
    )


def test_real_2b_exit_planner_rejects_changed_current_projection() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.domain.contracts import verified_contract_rule
    from pa_agent.research_backtest.domain.enums import ExecutionRejectionReason
    from pa_agent.research_backtest.domain.market_inputs import (
        target_event_watermark,
        target_minute_open_snapshot,
    )
    from pa_agent.research_backtest.planning.exits import (
        ExitPlanningInputs,
        build_exit_execution_plan,
    )
    from pa_agent.research_backtest.simulation.planning import (
        make_scheduled_exit_intent_factory,
    )
    from pa_agent.research_backtest.simulation.positions import (
        exit_execution_position_snapshot,
    )
    from tests.research_backtest.execution.fixtures.entry_plan_case import (
        complete_entry_inputs,
    )

    position = _position()
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    intent = make_scheduled_exit_intent_factory(
        execution,
        computational_experiment_id="e" * 64,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )(
        position,
        (ScheduledExitReason.TIME_EXIT,),
        20_000_123,
        object(),
    )
    template = complete_entry_inputs()
    target = intent.target_execution_time_utc_ms
    target_open = target_minute_open_snapshot(
        symbol=position.symbol,
        open_time_utc_ms=target,
        open_price=Decimal("123.45"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    watermark = target_event_watermark(
        symbol=position.symbol,
        target_open_time_utc_ms=target,
        event_watermark_time_utc_ms=target,
        watermark_source_event_id="scheduled-exit-watermark",
        watermark_source_stream_version="BINANCE_TRADE_WATERMARK_V1",
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    changed = replace(position, quantity=position.quantity / Decimal("2"))
    result = build_exit_execution_plan(
        ExitPlanningInputs(
            intent=intent,
            target_open=target_open,
            watermark=watermark,
            contract=verified_contract_rule(
                symbol=template.contract.symbol,
                query_time_utc_ms=target,
                source_kind=template.contract.source_kind,
                source_uri_or_archive_id=template.contract.source_uri_or_archive_id,
                source_content_hash=template.contract.source_content_hash,
                effective_from_utc_ms=template.contract.effective_from_utc_ms,
                effective_to_utc_ms=target + 1,
                rule_version=template.contract.rule_version,
                tick_size=template.contract.tick_size,
                step_size=template.contract.step_size,
                min_qty=template.contract.min_qty,
                min_notional=template.contract.min_notional,
                quantity_precision_audit=template.contract.quantity_precision_audit,
                price_precision_audit=template.contract.price_precision_audit,
                evidence_manifest_hash=template.contract.evidence_manifest_hash,
            ),
            cost=template.cost,
            target_position_snapshot_hash=exit_execution_position_snapshot(
                changed
            ).snapshot_content_hash,
            code_commit="c" * 40,
            dependency_lock_hash="b" * 64,
            stage=ResearchStage.BACKTEST,
        )
    )
    assert result.reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED


def test_full_production_chain_survives_funding_and_executes_real_time_exit() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.domain.contracts import verified_contract_rule
    from pa_agent.research_backtest.domain.enums import TrendState
    from pa_agent.research_backtest.domain.market_inputs import (
        target_event_watermark,
        target_minute_open_snapshot,
    )
    from pa_agent.research_backtest.simulation.context import (
        make_production_run_context,
        run_production_simulation,
    )
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
    )
    from pa_agent.research_backtest.simulation.funding import FundingRecord
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteBar,
        MinuteInputSlice,
        SimulationInputs,
    )
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence
    from pa_agent.research_backtest.simulation.planning import (
        TrendEvidence,
        build_entry_batch_planning_outcome,
        make_scheduled_exit_intent_factory,
    )
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
    from tests.research_backtest.simulation.test_production_evidence_bridge import (
        _catalog_and_inputs,
    )

    _, entries = _catalog_and_inputs()
    entry = entries[0]
    plan = build_entry_batch_planning_outcome(_batch_inputs()).plans[0]
    position = position_from_entry_plan(plan)
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    probe_intent = make_scheduled_exit_intent_factory(
        execution,
        computational_experiment_id="f" * 64,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )(
        position,
        (ScheduledExitReason.TIME_EXIT,),
        position.maximum_exit_time_utc_ms,
        object(),
    )
    exit_time = probe_intent.target_execution_time_utc_ms
    exit_open = target_minute_open_snapshot(
        symbol=entry.intent.symbol,
        open_time_utc_ms=exit_time,
        open_price=entry.target_open.open_price,
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )
    exit_watermark = target_event_watermark(
        symbol=entry.intent.symbol,
        target_open_time_utc_ms=exit_time,
        event_watermark_time_utc_ms=exit_time,
        watermark_source_event_id="time-exit-watermark",
        watermark_source_stream_version="BINANCE_TRADE_WATERMARK_V1",
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )
    contract = entry.contract
    exit_contract = verified_contract_rule(
        symbol=contract.symbol,
        query_time_utc_ms=exit_time,
        source_kind=contract.source_kind,
        source_uri_or_archive_id=contract.source_uri_or_archive_id,
        source_content_hash=contract.source_content_hash,
        effective_from_utc_ms=contract.effective_to_utc_ms,
        effective_to_utc_ms=exit_time + 60_000,
        rule_version=contract.rule_version,
        tick_size=contract.tick_size,
        step_size=contract.step_size,
        min_qty=contract.min_qty,
        min_notional=contract.min_notional,
        quantity_precision_audit=contract.quantity_precision_audit,
        price_precision_audit=contract.price_precision_audit,
        evidence_manifest_hash=contract.evidence_manifest_hash,
    )
    maintenance = MaintenanceEvidence(
        symbol=entry.intent.symbol,
        effective_start_utc_ms=0,
        effective_end_utc_ms=exit_time + 60_000,
        notional_floor=Decimal("0"),
        notional_cap=Decimal("1000000"),
        maintenance_margin_rate=Decimal("0.005"),
        source_hash="8" * 64,
        mode="APPROXIMATED",
        version="MMR_V1",
    )
    catalog = make_simulation_evidence_catalog(
        target_opens=(entry.target_open, exit_open),
        watermarks=(entry.watermark, exit_watermark),
        contracts=(entry.contract, exit_contract),
        costs=(entry.cost,),
        funding_schedules=(entry.funding_schedule,),
        funding_risks=(entry.funding_risk,),
        maintenance=(maintenance,),
        stage=entry.stage,
        split_start_utc_ms=0,
        split_end_utc_ms=exit_time,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )
    funding_time = next(
        window.nominal_time_utc_ms
        for window in entry.funding_schedule.settlement_windows
        if TARGET_TIME < window.nominal_time_utc_ms < position.maximum_exit_time_utc_ms
    )
    price = entry.target_open.open_price

    def minute_at(event_time: int) -> MinuteInputSlice:
        trade = MinuteBar(
            symbol=entry.intent.symbol,
            open_time_utc_ms=event_time,
            close_time_utc_ms=event_time + 59_999,
            open=price,
            high=price,
            low=price,
            close=price,
            is_closed=True,
            content_hash=f"{event_time:064x}"[-64:],
        )
        mark = replace(trade, content_hash=f"{event_time + 1:064x}"[-64:])
        funding = (
            (
                FundingRecord(
                    record_id="funding-before-time-exit",
                    symbol=entry.intent.symbol,
                    funding_time_utc_ms=event_time,
                    funding_rate=Decimal("0.00001"),
                    mark_price=price,
                    content_hash="6" * 64,
                ),
            )
            if event_time == funding_time
            else ()
        )
        trend = (
            (
                TrendEvidence(
                    decision_time_utc_ms=event_time + 59_999,
                    trend_state=TrendState.BULL,
                    is_closed=True,
                    content_hash=f"{event_time + 2:064x}"[-64:],
                    symbol=entry.intent.symbol,
                ),
            )
            if event_time >= TARGET_TIME and (event_time + 60_000) % 14_400_000 == 0
            else ()
        )
        return MinuteInputSlice(
            event_time,
            (trade,),
            (mark,),
            funding,
            (),
            trend_evidence=trend,
        )

    start = TARGET_TIME - 60_000
    inputs = SimulationInputs(
        tuple(minute_at(time) for time in range(start, exit_time + 60_000, 60_000)),
        (entry.candidate,),
        (),
    )
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": start,
                "simulation_end_exit_open_utc_ms": exit_time,
                "two_a_version": "INDICATOR_CONFIG_V1",
                "two_b_planner_version": "2B_CANONICAL_VERSION_V1",
                "two_b_planner_config_hash": execution.config_content_hash,
                "two_c_engine_version": "MINUTE_ENGINE_V1",
                "code_commit": catalog.code_commit,
                "dependency_lock_hash": catalog.dependency_lock_hash,
            }
        )
    )
    context = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    result = run_production_simulation(inputs, context)
    for path in result.paths:
        assert path.path_result.path_state.value == "VALID", (
            path.path_result,
            path.minute_results[-1].planning_outputs,
        )
        all_fills = tuple(fill for minute in path.minute_results for fill in minute.fills)
        all_trades = tuple(trade for minute in path.minute_results for trade in minute.trades)
        assert len(all_fills) == 2
        assert len(all_trades) == 1
        assert all_trades[0].exit_reason is ScheduledExitReason.TIME_EXIT
        assert all_trades[0].funding != 0
