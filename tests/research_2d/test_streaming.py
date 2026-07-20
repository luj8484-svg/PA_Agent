from dataclasses import replace
from decimal import Decimal

from pa_agent.research_2d.streaming import run_streaming_paths


def test_streaming_adapter_matches_frozen_2c_terminal_economics() -> None:
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.context import (
        make_production_run_context,
        run_production_simulation,
    )
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteBar,
        MinuteInputSlice,
        SimulationInputs,
    )
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence
    from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
    from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
    from tests.research_backtest.simulation.test_production_evidence_bridge import (
        _catalog_and_inputs,
    )

    _, entries = _catalog_and_inputs()
    entry = entries[0]
    start, end = TARGET_TIME - 60_000, TARGET_TIME + 60_000
    maintenance = tuple(
        MaintenanceEvidence(
            item.intent.symbol,
            0,
            end + 60_000,
            Decimal("0"),
            Decimal("1000000"),
            Decimal("0.005"),
            ("8" if item.intent.symbol == "BTCUSDT" else "7") * 64,
            "APPROXIMATED",
            "MMR_V1",
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

    def minute_at(time: int, exit_minute: bool = False) -> MinuteInputSlice:
        trades = tuple(
            MinuteBar(
                item.intent.symbol,
                time,
                time + 59_999,
                Decimal("200")
                if exit_minute and item.intent.symbol == "BTCUSDT"
                else Decimal("1")
                if exit_minute
                else item.target_open.open_price,
                Decimal("200")
                if exit_minute and item.intent.symbol == "BTCUSDT"
                else Decimal("1")
                if exit_minute
                else item.target_open.open_price,
                Decimal("200")
                if exit_minute and item.intent.symbol == "BTCUSDT"
                else Decimal("1")
                if exit_minute
                else item.target_open.open_price,
                Decimal("200")
                if exit_minute and item.intent.symbol == "BTCUSDT"
                else Decimal("1")
                if exit_minute
                else item.target_open.open_price,
                True,
                f"{time + index:064x}"[-64:],
            )
            for index, item in enumerate(entries)
        )
        return MinuteInputSlice(
            time,
            trades,
            tuple(
                replace(item, content_hash=f"{time + index + 10:064x}"[-64:])
                for index, item in enumerate(trades)
            ),
            (),
            (),
        )

    minutes = (minute_at(start), minute_at(TARGET_TIME), minute_at(end, True))
    inputs = SimulationInputs(minutes, tuple(item.candidate for item in entries), ())
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": start,
                "simulation_end_exit_open_utc_ms": end,
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
    frozen = run_production_simulation(inputs, context)
    streamed = run_streaming_paths(context, minutes)
    for expected, actual in zip(frozen.paths, streamed, strict=True):
        assert actual.state == expected.minute_results[-1].state
        assert actual.fills == tuple(
            fill for minute in expected.minute_results for fill in minute.fills
        )
        assert actual.trades == tuple(
            trade for minute in expected.minute_results for trade in minute.trades
        )
        assert actual.ledger_entries == tuple(
            row for minute in expected.minute_results for row in minute.ledger_entries
        )
        assert actual.path_result == expected.path_result
