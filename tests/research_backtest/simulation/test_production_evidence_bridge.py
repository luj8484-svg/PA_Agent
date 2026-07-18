from dataclasses import replace
from decimal import Decimal

from pa_agent.research_backtest.domain.enums import MarketView
from tests.research_backtest.execution.fixtures.entry_plan_case import (
    TARGET_TIME,
    complete_entry_inputs,
)
from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
from tests.research_backtest.simulation.test_inputs_and_invalid import bar


def _catalog_and_inputs():
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
    )

    btc = complete_entry_inputs()
    eth = complete_entry_inputs(
        symbol="ETHUSDT",
        market_view=MarketView.SHORT,
        atr14_4h=Decimal("1"),
        decision_close_override=Decimal("20"),
    )
    catalog = make_simulation_evidence_catalog(
        target_opens=(btc.target_open, eth.target_open),
        watermarks=(btc.watermark, eth.watermark),
        contracts=(btc.contract, eth.contract),
        costs=(btc.cost, eth.cost),
        funding_schedules=(btc.funding_schedule, eth.funding_schedule),
        funding_risks=(btc.funding_risk, eth.funding_risk),
        maintenance=(),
        stage=btc.stage,
        split_start_utc_ms=btc.split_start_utc_ms,
        split_end_utc_ms=btc.split_end_utc_ms,
        code_commit=btc.code_commit,
        dependency_lock_hash=btc.dependency_lock_hash,
    )
    return catalog, (btc, eth)


def _minute(entries):
    from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

    trade = tuple(
        replace(
            bar(),
            symbol=item.intent.symbol,
            open_time_utc_ms=TARGET_TIME,
            close_time_utc_ms=TARGET_TIME + 59_999,
            open=item.target_open.open_price,
            high=item.target_open.open_price,
            low=item.target_open.open_price,
            close=item.target_open.open_price,
        )
        for item in entries
    )
    mark = tuple(replace(item, content_hash="9" * 64) for item in trade)
    return MinuteInputSlice(TARGET_TIME, trade, mark, (), ())


def test_bridge_replays_current_engine_account_and_builds_real_2b_batch() -> None:
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )
    from pa_agent.research_backtest.simulation.evidence import (
        build_entry_batch_inputs_from_engine,
    )
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )

    catalog, entries = _catalog_and_inputs()
    config = make_simulation_config(**config_payload())
    state = initial_engine_state(config)
    batch_inputs = build_entry_batch_inputs_from_engine(
        state=state,
        due_intents=tuple(item.intent for item in entries),
        minute=_minute(entries),
        candidates=tuple(item.candidate for item in entries),
        catalog=catalog,
    )
    outcome = build_entry_batch_planning_outcome(batch_inputs)
    assert batch_inputs.account.wallet_balance == state.wallet_balance
    assert batch_inputs.account.available_balance == Decimal("10000")
    assert len({item.account.snapshot_id for item in outcome.plan_inputs}) == 1
    assert tuple(item.symbol for item in outcome.plans) == ("BTCUSDT", "ETHUSDT")


def test_bridge_rejects_future_or_mismatched_target_open() -> None:
    import pytest

    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )
    from pa_agent.research_backtest.simulation.evidence import (
        build_entry_batch_inputs_from_engine,
    )

    catalog, entries = _catalog_and_inputs()
    config = make_simulation_config(**config_payload())
    minute = _minute(entries)
    wrong = replace(
        minute,
        trade_bars=(
            replace(minute.trade_bars[0], open=Decimal("999"), high=Decimal("999")),
            *minute.trade_bars[1:],
        ),
    )
    with pytest.raises(ValueError, match="target-open evidence"):
        build_entry_batch_inputs_from_engine(
            state=initial_engine_state(config),
            due_intents=tuple(item.intent for item in entries),
            minute=wrong,
            candidates=tuple(item.candidate for item in entries),
            catalog=catalog,
        )


def test_position_preserves_origin_planned_risk_for_open_risk_replay() -> None:
    from pa_agent.research_backtest.simulation.planning import (
        build_entry_batch_planning_outcome,
    )
    from pa_agent.research_backtest.simulation.positions import position_from_entry_plan
    from tests.research_backtest.simulation.test_entry_batch_adapter import _batch_inputs

    plan = build_entry_batch_planning_outcome(_batch_inputs()).plans[0]
    position = position_from_entry_plan(plan)
    assert position.planned_risk == plan.planned_risk


def test_production_planner_dependencies_use_engine_bridge_by_default() -> None:
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )
    from pa_agent.research_backtest.simulation.evidence import (
        production_planning_evidence_factory,
    )
    from pa_agent.research_backtest.simulation.planning import (
        plan_due_entry_batch,
        production_planner_dependencies,
    )

    catalog, entries = _catalog_and_inputs()
    minute = _minute(entries)
    state = initial_engine_state(make_simulation_config(**config_payload()))
    evidence = production_planning_evidence_factory(catalog)(state, minute)
    deps = production_planner_dependencies(
        catalog,
        tuple(item.candidate for item in entries),
    )
    outcome = plan_due_entry_batch(
        state,
        tuple(item.intent for item in entries),
        TARGET_TIME,
        evidence,
        deps,
    )
    assert tuple(item.symbol for item in outcome.plans) == ("BTCUSDT", "ETHUSDT")


def test_complete_run_uses_real_candidate_2b_bridge_fill_exit_and_manifest(tmp_path) -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.engine import EngineDependencies, run_simulation
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
        production_execution_cost_factory,
        production_maintenance_evidence_factory,
        production_planning_evidence_factory,
    )
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteBar,
        MinuteInputSlice,
        SimulationInputs,
    )
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence
    from pa_agent.research_backtest.simulation.output import write_canonical_result
    from pa_agent.research_backtest.simulation.planning import (
        make_candidate_intent_factory,
        production_planner_dependencies,
    )

    _, entries = _catalog_and_inputs()
    entry = entries[0]
    start = TARGET_TIME - 60_000
    end = TARGET_TIME + 60_000
    maintenance = tuple(
        MaintenanceEvidence(
            symbol=item.intent.symbol,
            effective_start_utc_ms=0,
            effective_end_utc_ms=end + 60_000,
            notional_floor=Decimal("0"),
            notional_cap=Decimal("1000000"),
            maintenance_margin_rate=Decimal("0.005"),
            source_hash=("8" if item.intent.symbol == "BTCUSDT" else "7") * 64,
            mode="APPROXIMATED",
            version="MMR_V1",
        )
        for item in entries
    )
    catalog = make_simulation_evidence_catalog(
        target_opens=tuple(item.target_open for item in entries),
        watermarks=tuple(item.watermark for item in entries),
        contracts=tuple(item.contract for item in entries),
        costs=tuple(item.cost for item in entries),
        funding_schedules=tuple(item.funding_schedule for item in entries),
        funding_risks=tuple(item.funding_risk for item in entries),
        maintenance=maintenance,
        stage=entry.stage,
        split_start_utc_ms=entry.split_start_utc_ms,
        split_end_utc_ms=entry.split_end_utc_ms,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )

    def minute_at(event_time: int, *, exit_minute: bool = False) -> MinuteInputSlice:
        trades = tuple(
            MinuteBar(
                symbol=item.intent.symbol,
                open_time_utc_ms=event_time,
                close_time_utc_ms=event_time + 59_999,
                open=(Decimal("200") if item.intent.symbol == "BTCUSDT" else Decimal("1"))
                if exit_minute
                else item.target_open.open_price,
                high=(Decimal("200") if item.intent.symbol == "BTCUSDT" else Decimal("1"))
                if exit_minute
                else item.target_open.open_price,
                low=(Decimal("200") if item.intent.symbol == "BTCUSDT" else Decimal("1"))
                if exit_minute
                else item.target_open.open_price,
                close=(Decimal("200") if item.intent.symbol == "BTCUSDT" else Decimal("1"))
                if exit_minute
                else item.target_open.open_price,
                is_closed=True,
                content_hash=(f"{event_time + index:064x}"[-64:]),
            )
            for index, item in enumerate(entries)
        )
        marks = tuple(
            replace(trade, content_hash=(f"{event_time + 10 + index:064x}"[-64:]))
            for index, trade in enumerate(trades)
        )
        return MinuteInputSlice(event_time, trades, marks, (), ())

    inputs = SimulationInputs(
        (
            minute_at(start),
            minute_at(TARGET_TIME),
            minute_at(end, exit_minute=True),
        ),
        tuple(item.candidate for item in entries),
        (),
    )
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": start,
                "simulation_end_exit_open_utc_ms": end,
            }
        )
    )
    planner_dependencies = production_planner_dependencies(
        catalog, tuple(item.candidate for item in entries)
    )
    dependencies = EngineDependencies(
        planners=planner_dependencies,
        entry_intent_factory=make_candidate_intent_factory(
            execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1),
            computational_experiment_id="f" * 64,
            stage=entry.stage,
            code_commit=entry.code_commit,
            dependency_lock_hash=entry.dependency_lock_hash,
        ),
        exit_intent_factory=None,
        planning_evidence_factory=production_planning_evidence_factory(catalog),
        maintenance_evidence_factory=production_maintenance_evidence_factory(catalog),
        execution_cost_factory=production_execution_cost_factory(catalog),
        evidence_catalog=catalog,
    )
    result = run_simulation(inputs, config, dependencies)
    assert all(path.path_result.path_state.value == "VALID" for path in result.paths), tuple(
        path.path_result for path in result.paths
    )
    assert all(len(path.minute_results) == 3 for path in result.paths)
    assert all(sum(len(item.fills) for item in path.minute_results) == 4 for path in result.paths)
    assert all(sum(len(item.trades) for item in path.minute_results) == 2 for path in result.paths)
    from tests.research_backtest.simulation.golden_support import assert_full_golden

    assert_full_golden(
        "BTC_ETH_SAME_MINUTE_BATCH",
        input_fixture=(inputs, catalog, config),
        event_sequence=tuple(item.events for path in result.paths for item in path.minute_results),
        ledger=tuple(item.ledger_entries for path in result.paths for item in path.minute_results),
        fill_trade={
            "fills": tuple(item.fills for path in result.paths for item in path.minute_results),
            "trades": tuple(item.trades for path in result.paths for item in path.minute_results),
        },
        equity=tuple(item.equity_points for path in result.paths for item in path.minute_results),
        path_result=tuple(path.path_result for path in result.paths),
    )
    manifest = write_canonical_result(result, tmp_path)
    assert manifest.simulation_run_id == result.simulation_run_id
    assert (tmp_path / "state_snapshots.jsonl").exists()
