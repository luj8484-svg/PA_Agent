from dataclasses import fields, replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import ResearchStage
from tests.research_backtest.execution.fixtures.entry_plan_case import TARGET_TIME
from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
from tests.research_backtest.simulation.test_production_run_context import _production_case


def _catalog_with_stage(catalog, stage):
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog

    return make_simulation_evidence_catalog(
        target_opens=catalog.target_opens,
        watermarks=catalog.watermarks,
        contracts=catalog.contracts,
        costs=catalog.costs,
        funding_schedules=catalog.funding_schedules,
        funding_risks=catalog.funding_risks,
        maintenance=catalog.maintenance,
        stage=stage,
        split_start_utc_ms=catalog.split_start_utc_ms,
        split_end_utc_ms=catalog.split_end_utc_ms,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )


def _full_entry_case():
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import make_simulation_evidence_catalog
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteBar,
        MinuteInputSlice,
        SimulationInputs,
    )
    from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence
    from tests.research_backtest.simulation.test_production_evidence_bridge import (
        _catalog_and_inputs,
    )

    _, entries = _catalog_and_inputs()
    entry = entries[0]
    start = TARGET_TIME - 60_000
    end = TARGET_TIME + 60_000
    maintenance = MaintenanceEvidence(
        symbol=entry.intent.symbol,
        effective_start_utc_ms=0,
        effective_end_utc_ms=end + 60_000,
        notional_floor=Decimal("0"),
        notional_cap=Decimal("1000000"),
        maintenance_margin_rate=Decimal("0.005"),
        source_hash="8" * 64,
        mode="APPROXIMATED",
        version="MMR_V1",
    )
    catalog = make_simulation_evidence_catalog(
        target_opens=(entry.target_open,),
        watermarks=(entry.watermark,),
        contracts=(entry.contract,),
        costs=(entry.cost,),
        funding_schedules=(entry.funding_schedule,),
        funding_risks=(entry.funding_risk,),
        maintenance=(maintenance,),
        stage=ResearchStage.BACKTEST,
        split_start_utc_ms=entry.split_start_utc_ms,
        split_end_utc_ms=entry.split_end_utc_ms,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )

    def minute_at(event_time):
        price = entry.target_open.open_price
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
        return MinuteInputSlice(
            event_time,
            (trade,),
            (replace(trade, content_hash=f"{event_time + 1:064x}"[-64:]),),
            (),
            (),
        )

    inputs = SimulationInputs(
        (minute_at(start), minute_at(TARGET_TIME), minute_at(end)),
        (entry.candidate,),
        (),
    )
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
    return inputs, config, catalog, execution


def _planning_and_fill_ids(result):
    return tuple(
        getattr(item, name)
        for path in result.paths
        for minute in path.minute_results
        for item in (*minute.planning_outputs, *minute.fills)
        for name in ("intent_id", "plan_id", "fill_id")
        if hasattr(item, name)
    )


def test_computational_experiment_id_changes_identity_run_and_outputs(tmp_path) -> None:
    from pa_agent.research_backtest.simulation.context import (
        make_production_run_context,
        run_production_simulation,
    )
    from pa_agent.research_backtest.simulation.output import write_canonical_result

    inputs, config, catalog, execution = _full_entry_case()
    contexts = tuple(
        make_production_run_context(
            inputs=inputs,
            config=config,
            evidence_catalog=catalog,
            execution_time_config=execution,
            computational_experiment_id=value * 64,
        )
        for value in ("f", "e")
    )
    results = tuple(run_production_simulation(inputs, context) for context in contexts)
    manifests = tuple(
        write_canonical_result(result, tmp_path / str(index))
        for index, result in enumerate(results)
    )

    assert contexts[0].input_identity != contexts[1].input_identity
    assert results[0].simulation_run_id != results[1].simulation_run_id
    assert _planning_and_fill_ids(results[0]) != _planning_and_fill_ids(results[1])
    assert manifests[0].simulation_run_id != manifests[1].simulation_run_id
    assert manifests[0].result_content_hash != manifests[1].result_content_hash


def test_same_computational_experiment_id_is_fully_deterministic(tmp_path) -> None:
    from pa_agent.research_backtest.simulation.context import (
        make_production_run_context,
        run_production_simulation,
    )
    from pa_agent.research_backtest.simulation.output import write_canonical_result

    inputs, config, catalog, execution = _full_entry_case()
    context = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    results = tuple(run_production_simulation(inputs, context) for _ in range(2))
    manifests = tuple(
        write_canonical_result(result, tmp_path / str(index))
        for index, result in enumerate(results)
    )
    assert results[0] == results[1]
    assert results[0].simulation_run_id == results[1].simulation_run_id
    assert manifests[0].result_content_hash == manifests[1].result_content_hash
    assert _planning_and_fill_ids(results[0]) == _planning_and_fill_ids(results[1])


@pytest.mark.parametrize(
    "stage", (ResearchStage.PAPER_SIMULATION, ResearchStage.LIVE_ELIGIBILITY_RESEARCH)
)
def test_production_context_rejects_non_backtest_stage_before_paths(stage) -> None:
    from pa_agent.research_backtest.simulation.context import (
        RunConfigurationMismatch,
        make_production_run_context,
    )

    inputs, config, catalog, execution = _production_case()
    with pytest.raises(RunConfigurationMismatch, match="BACKTEST"):
        make_production_run_context(
            inputs=inputs,
            config=config,
            evidence_catalog=_catalog_with_stage(catalog, stage),
            execution_time_config=execution,
            computational_experiment_id="f" * 64,
        )


def _forged_identity(identity, field, value):
    from pa_agent.research_backtest.simulation.identity import make_simulation_input_identity

    payload = {
        item.name: getattr(identity, item.name)
        for item in fields(identity)
        if item.name not in {"schema_version", "input_identity_id", "input_identity_content_hash"}
    }
    payload[field] = value
    return make_simulation_input_identity(**payload)


@pytest.mark.parametrize(
    "field",
    (
        "planner_identity_content_hash",
        "two_a_identity_content_hash",
        "two_b_identity_content_hash",
        "two_c_identity_content_hash",
    ),
)
def test_direct_self_consistent_forged_production_context_identity_fails(field) -> None:
    from pa_agent.research_backtest.simulation.context import (
        ProductionRunContext,
        RunConfigurationMismatch,
        make_production_run_context,
    )

    inputs, config, catalog, execution = _production_case()
    context = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    forged_hash = canonical_sha256({"forged": field})
    forged_identity = _forged_identity(context.input_identity, field, forged_hash)
    values = {item.name: getattr(context, item.name) for item in fields(context)}
    values[field] = forged_hash
    values["input_identity"] = forged_identity
    with pytest.raises(RunConfigurationMismatch, match="identity"):
        ProductionRunContext(**values)


def test_production_context_requires_sha256_computational_experiment_id() -> None:
    from pa_agent.research_backtest.simulation.context import make_production_run_context

    inputs, config, catalog, execution = _production_case()
    with pytest.raises(ValueError, match="computational_experiment_id"):
        make_production_run_context(
            inputs=inputs,
            config=config,
            evidence_catalog=catalog,
            execution_time_config=execution,
            computational_experiment_id="not-a-sha256",
        )
