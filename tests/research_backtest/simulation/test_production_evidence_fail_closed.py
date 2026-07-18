from dataclasses import replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ResearchStage,
    ScheduledExitReason,
    Side,
)
from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
from tests.research_backtest.simulation.test_scheduled_exit_production import _position


def _exit_case(*, catalog_mutator=lambda value: value, position_mutator=lambda value: value):
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.domain.contracts import verified_contract_rule
    from pa_agent.research_backtest.domain.market_inputs import (
        target_event_watermark,
        target_minute_open_snapshot,
    )
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )
    from pa_agent.research_backtest.simulation.engine import EngineDependencies
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
        production_execution_cost_factory,
        production_maintenance_evidence_factory,
        production_planning_evidence_factory,
    )
    from pa_agent.research_backtest.simulation.inputs import MinuteBar, MinuteInputSlice
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence
    from pa_agent.research_backtest.simulation.planning import (
        make_scheduled_exit_intent_factory,
        production_planner_dependencies,
    )
    from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs

    original = _position()
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    intent = make_scheduled_exit_intent_factory(
        execution,
        computational_experiment_id="f" * 64,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )(
        original,
        (ScheduledExitReason.TIME_EXIT,),
        20_000_123,
        object(),
    )
    target = intent.target_execution_time_utc_ms
    current = position_mutator(original)
    template = complete_entry_inputs()
    open_price = current.entry_price
    target_open = target_minute_open_snapshot(
        symbol=current.symbol,
        open_time_utc_ms=target,
        open_price=open_price,
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    watermark = target_event_watermark(
        symbol=current.symbol,
        target_open_time_utc_ms=target,
        event_watermark_time_utc_ms=target,
        watermark_source_event_id="fail-closed-watermark",
        watermark_source_stream_version="BINANCE_TRADE_WATERMARK_V1",
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    contract = verified_contract_rule(
        symbol=current.symbol,
        query_time_utc_ms=target,
        source_kind=template.contract.source_kind,
        source_uri_or_archive_id=template.contract.source_uri_or_archive_id,
        source_content_hash=template.contract.source_content_hash,
        effective_from_utc_ms=0,
        effective_to_utc_ms=target + 60_000,
        rule_version=template.contract.rule_version,
        tick_size=template.contract.tick_size,
        step_size=template.contract.step_size,
        min_qty=template.contract.min_qty,
        min_notional=template.contract.min_notional,
        quantity_precision_audit=template.contract.quantity_precision_audit,
        price_precision_audit=template.contract.price_precision_audit,
        evidence_manifest_hash=template.contract.evidence_manifest_hash,
    )
    maintenance = MaintenanceEvidence(
        symbol=current.symbol,
        effective_start_utc_ms=0,
        effective_end_utc_ms=target + 60_000,
        notional_floor=Decimal("0"),
        notional_cap=Decimal("100000000"),
        maintenance_margin_rate=Decimal("0.005"),
        source_hash="8" * 64,
        mode="APPROXIMATED",
        version="MMR_V1",
    )
    catalog = make_simulation_evidence_catalog(
        target_opens=(target_open,),
        watermarks=(watermark,),
        contracts=(contract,),
        costs=(template.cost,),
        funding_schedules=(),
        funding_risks=(),
        maintenance=(maintenance,),
        stage=ResearchStage.BACKTEST,
        split_start_utc_ms=target,
        split_end_utc_ms=target,
        code_commit="c" * 40,
        dependency_lock_hash="b" * 64,
    )
    catalog = catalog_mutator(catalog)
    trade = MinuteBar(
        symbol=current.symbol,
        open_time_utc_ms=target,
        close_time_utc_ms=target + 59_999,
        open=open_price,
        high=open_price,
        low=open_price,
        close=open_price,
        is_closed=True,
        content_hash="7" * 64,
    )
    minute = MinuteInputSlice(target, (trade,), (replace(trade, content_hash="9" * 64),), (), ())
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": target,
                "simulation_end_exit_open_utc_ms": target,
            }
        )
    )
    state = replace(
        initial_engine_state(config),
        positions=(current,),
        pending_exit_intents=(intent,),
        pending_exit_reason_matches=((intent.intent_id, (ScheduledExitReason.TIME_EXIT,)),),
        locked_initial_margin=current.initial_margin,
        locked_fee_reserve=current.remaining_fee_reserve,
        locked_funding_reserve=current.remaining_funding_reserve,
    )
    dependencies = EngineDependencies(
        planners=production_planner_dependencies(catalog, ()),
        entry_intent_factory=None,
        exit_intent_factory=None,
        planning_evidence_factory=production_planning_evidence_factory(catalog),
        maintenance_evidence_factory=production_maintenance_evidence_factory(catalog),
        execution_cost_factory=production_execution_cost_factory(catalog),
        evidence_catalog=catalog,
        catalog_id=catalog.catalog_id,
        catalog_content_hash=catalog.catalog_content_hash,
    )
    return state, minute, config, dependencies


@pytest.mark.parametrize(
    "position_mutator",
    (
        lambda value: replace(value, quantity=value.quantity / Decimal("2")),
        lambda value: replace(
            value,
            side=Side.SHORT,
            stop_trigger_price=value.entry_price * Decimal("2"),
            take_profit_trigger_price=value.entry_price / Decimal("2"),
        ),
    ),
)
def test_real_production_exit_geometry_change_is_formal_invalid_path(position_mutator) -> None:
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent

    state, minute, config, dependencies = _exit_case(position_mutator=position_mutator)
    result = process_minute(state, minute, config, dependencies)

    rejection = next(item for item in result.planning_outputs if hasattr(item, "rejection_id"))
    invalid = next(item for item in result.planning_outputs if isinstance(item, PathInvalidEvent))
    assert rejection.reason is ExecutionRejectionReason.POSITION_SNAPSHOT_CHANGED
    assert rejection.disposition.value == "PLAN_CANCELLED"
    assert invalid.rejection_id == rejection.rejection_id
    assert invalid.rejection_reason == rejection.reason.value
    assert invalid.rejection_disposition == rejection.disposition.value
    assert invalid.rejection_stage == ResearchStage.BACKTEST.value
    assert result.state.path_state.value == "INVALID"
    assert result.fills == ()


def test_missing_exit_target_open_is_formal_rejection_not_value_error() -> None:
    from pa_agent.research_backtest.simulation.engine import process_minute

    def remove_target(catalog):
        from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog

        return make_simulation_evidence_catalog(
            target_opens=(),
            watermarks=catalog.watermarks,
            contracts=catalog.contracts,
            costs=catalog.costs,
            funding_schedules=catalog.funding_schedules,
            funding_risks=catalog.funding_risks,
            maintenance=catalog.maintenance,
            stage=catalog.stage,
            split_start_utc_ms=catalog.split_start_utc_ms,
            split_end_utc_ms=catalog.split_end_utc_ms,
            code_commit=catalog.code_commit,
            dependency_lock_hash=catalog.dependency_lock_hash,
        )

    state, minute, config, dependencies = _exit_case(catalog_mutator=remove_target)
    result = process_minute(state, minute, config, dependencies)
    rejection = next(item for item in result.planning_outputs if hasattr(item, "rejection_id"))
    assert rejection.reason is ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE
    assert result.state.path_state.value == "INVALID"
    assert result.fills == ()


def test_missing_exit_cost_is_formal_rejection_not_value_error() -> None:
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog

    def remove_cost(catalog):
        return make_simulation_evidence_catalog(
            target_opens=catalog.target_opens,
            watermarks=catalog.watermarks,
            contracts=catalog.contracts,
            costs=(),
            funding_schedules=catalog.funding_schedules,
            funding_risks=catalog.funding_risks,
            maintenance=catalog.maintenance,
            stage=catalog.stage,
            split_start_utc_ms=catalog.split_start_utc_ms,
            split_end_utc_ms=catalog.split_end_utc_ms,
            code_commit=catalog.code_commit,
            dependency_lock_hash=catalog.dependency_lock_hash,
        )

    state, minute, config, dependencies = _exit_case(catalog_mutator=remove_cost)
    result = process_minute(state, minute, config, dependencies)
    rejection = next(item for item in result.planning_outputs if hasattr(item, "rejection_id"))
    assert rejection.reason is ExecutionRejectionReason.COST_MODEL_UNAVAILABLE
    assert result.state.path_state.value == "INVALID"


@pytest.mark.parametrize("field", ("target_opens", "contracts"))
def test_duplicate_exit_evidence_is_data_invalid_not_value_error(field) -> None:
    from pa_agent.research_backtest.simulation.engine import process_minute
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog

    def duplicate(catalog):
        return make_simulation_evidence_catalog(
            target_opens=(
                catalog.target_opens * 2 if field == "target_opens" else catalog.target_opens
            ),
            watermarks=catalog.watermarks,
            contracts=(catalog.contracts * 2 if field == "contracts" else catalog.contracts),
            costs=catalog.costs,
            funding_schedules=catalog.funding_schedules,
            funding_risks=catalog.funding_risks,
            maintenance=catalog.maintenance,
            stage=catalog.stage,
            split_start_utc_ms=catalog.split_start_utc_ms,
            split_end_utc_ms=catalog.split_end_utc_ms,
            code_commit=catalog.code_commit,
            dependency_lock_hash=catalog.dependency_lock_hash,
        )

    state, minute, config, dependencies = _exit_case(catalog_mutator=duplicate)
    result = process_minute(state, minute, config, dependencies)
    rejection = next(item for item in result.planning_outputs if hasattr(item, "rejection_id"))
    assert rejection.reason is ExecutionRejectionReason.DATA_INVALID
    assert result.state.path_state.value == "INVALID"


@pytest.mark.parametrize("duplicate", (False, True))
def test_entry_catalog_missing_or_duplicate_target_open_returns_invalid_path(duplicate) -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.context import (
        make_production_run_context,
        run_production_simulation,
    )
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.simulation.test_production_evidence_bridge import (
        _catalog_and_inputs,
        _minute,
    )

    original_catalog, entries = _catalog_and_inputs()
    entry = entries[0]
    minute = _minute((entry,))
    start_minute = replace(
        minute,
        minute_open_utc_ms=TARGET_TIME - 60_000,
        trade_bars=tuple(
            replace(
                item,
                open_time_utc_ms=TARGET_TIME - 60_000,
                close_time_utc_ms=TARGET_TIME - 1,
            )
            for item in minute.trade_bars
        ),
        mark_bars=tuple(
            replace(
                item,
                open_time_utc_ms=TARGET_TIME - 60_000,
                close_time_utc_ms=TARGET_TIME - 1,
            )
            for item in minute.mark_bars
        ),
    )
    target_opens = (entry.target_open, entry.target_open) if duplicate else ()
    catalog = make_simulation_evidence_catalog(
        target_opens=target_opens,
        watermarks=(entry.watermark,),
        contracts=(entry.contract,),
        costs=(entry.cost,),
        funding_schedules=(entry.funding_schedule,),
        funding_risks=(entry.funding_risk,),
        maintenance=(),
        stage=ResearchStage.BACKTEST,
        split_start_utc_ms=original_catalog.split_start_utc_ms,
        split_end_utc_ms=original_catalog.split_end_utc_ms,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )
    end_minute = replace(
        minute,
        minute_open_utc_ms=TARGET_TIME + 60_000,
        trade_bars=tuple(
            replace(
                item,
                open_time_utc_ms=TARGET_TIME + 60_000,
                close_time_utc_ms=TARGET_TIME + 119_999,
            )
            for item in minute.trade_bars
        ),
        mark_bars=tuple(
            replace(
                item,
                open_time_utc_ms=TARGET_TIME + 60_000,
                close_time_utc_ms=TARGET_TIME + 119_999,
            )
            for item in minute.mark_bars
        ),
    )
    inputs = SimulationInputs((start_minute, minute, end_minute), (entry.candidate,), ())
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": TARGET_TIME - 60_000,
                "simulation_end_exit_open_utc_ms": TARGET_TIME + 60_000,
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
    assert all(path.path_result.path_state.value == "INVALID" for path in result.paths)
    expected = (
        ExecutionRejectionReason.DATA_INVALID.value
        if duplicate
        else ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE.value
    )
    assert all(expected in path.path_result.invalid_reason for path in result.paths)
