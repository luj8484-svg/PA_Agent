from dataclasses import replace

import pytest

from tests.research_backtest.simulation.test_domain_identity_scope import config_payload
from tests.research_backtest.simulation.test_production_evidence_bridge import (
    _catalog_and_inputs,
    _minute,
)


def _production_case():
    from pa_agent.research_backtest.domain.config import execution_time_config
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs

    catalog, entries = _catalog_and_inputs()
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    minute = _minute(entries)
    inputs = SimulationInputs((minute,), tuple(item.candidate for item in entries), ())
    config = make_simulation_config(
        **(
            config_payload()
            | {
                "simulation_start_utc_ms": minute.minute_open_utc_ms,
                "simulation_end_exit_open_utc_ms": minute.minute_open_utc_ms,
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


def _changed_config(config, **changes):
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    payload = {
        "symbols": config.symbols,
        "simulation_start_utc_ms": config.simulation_start_utc_ms,
        "simulation_end_exit_open_utc_ms": config.simulation_end_exit_open_utc_ms,
        "initial_wallet_balance": config.initial_wallet_balance,
        "cost_model_version": config.cost_model_version,
        "funding_model_version": config.funding_model_version,
        "two_a_version": config.two_a_version,
        "two_b_planner_version": config.two_b_planner_version,
        "two_b_planner_config_hash": config.two_b_planner_config_hash,
        "two_c_engine_version": config.two_c_engine_version,
        "code_commit": config.code_commit,
        "dependency_lock_hash": config.dependency_lock_hash,
    }
    return make_simulation_config(**(payload | changes))


def test_production_context_binds_actual_inputs_catalog_planner_and_versions() -> None:
    from pa_agent.research_backtest.simulation.context import (
        build_production_engine_dependencies,
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
    dependencies = build_production_engine_dependencies(context)

    assert context.candidates == inputs.candidates
    assert context.input_identity.evidence_catalog_id == catalog.catalog_id
    assert context.input_identity.evidence_catalog_content_hash == catalog.catalog_content_hash
    assert (
        context.input_identity.execution_time_config_content_hash == execution.config_content_hash
    )
    assert dependencies.evidence_catalog == catalog
    assert dependencies.catalog_id == catalog.catalog_id
    assert dependencies.catalog_content_hash == catalog.catalog_content_hash


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda config, catalog, execution: _changed_config(config, code_commit="d" * 40), "code"),
        (
            lambda config, catalog, execution: _changed_config(
                config, dependency_lock_hash="e" * 64
            ),
            "dependency",
        ),
        (
            lambda config, catalog, execution: _changed_config(
                config, two_b_planner_config_hash="0" * 64
            ),
            "ExecutionTimeConfig",
        ),
        (
            lambda config, catalog, execution: _changed_config(
                config, two_c_engine_version="MINUTE_ENGINE_WRONG"
            ),
            "2C",
        ),
    ),
)
def test_production_context_fails_closed_before_paths_on_identity_mismatch(
    mutation, message
) -> None:
    from pa_agent.research_backtest.simulation.context import (
        RunConfigurationMismatch,
        make_production_run_context,
    )

    inputs, config, catalog, execution = _production_case()
    bad = mutation(config, catalog, execution)
    with pytest.raises(RunConfigurationMismatch, match=message):
        make_production_run_context(
            inputs=inputs,
            config=bad,
            evidence_catalog=catalog,
            execution_time_config=execution,
            computational_experiment_id="f" * 64,
        )


def test_production_context_rejects_candidate_stream_substitution() -> None:
    from pa_agent.research_backtest.simulation.context import (
        RunConfigurationMismatch,
        make_production_run_context,
        run_production_simulation,
    )

    inputs, config, catalog, execution = _production_case()
    context = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    substituted = replace(inputs, candidates=inputs.candidates[:1])
    with pytest.raises(RunConfigurationMismatch, match="Candidate"):
        run_production_simulation(substituted, context)


@pytest.mark.parametrize(
    ("change", "value"),
    (
        ("stage", "PAPER_SIMULATION"),
        ("split_end_utc_ms", 1),
        ("code_commit", "0" * 40),
        ("dependency_lock_hash", "0" * 64),
    ),
)
def test_context_declaration_cannot_claim_a_different_catalog(change, value) -> None:
    from pa_agent.research_backtest.simulation.context import (
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
    with pytest.raises(RunConfigurationMismatch, match="declaration"):
        replace(context, **{change: value})


def test_target_open_or_watermark_change_changes_run_identity() -> None:
    from pa_agent.research_backtest.domain.market_inputs import target_event_watermark
    from pa_agent.research_backtest.simulation.context import make_production_run_context
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
    )

    inputs, config, catalog, execution = _production_case()
    first = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    changed_catalog = make_simulation_evidence_catalog(
        target_opens=catalog.target_opens,
        watermarks=tuple(
            target_event_watermark(
                symbol=item.symbol,
                target_open_time_utc_ms=item.target_open_time_utc_ms,
                event_watermark_time_utc_ms=item.event_watermark_time_utc_ms,
                watermark_source_event_id=item.watermark_source_event_id + "-changed",
                watermark_source_stream_version=item.watermark_source_stream_version,
                code_commit=item.code_commit,
                dependency_lock_hash=item.dependency_lock_hash,
            )
            if index == 0
            else item
            for index, item in enumerate(catalog.watermarks)
        ),
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
    second = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=changed_catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    assert (
        first.input_identity.input_identity_content_hash
        != second.input_identity.input_identity_content_hash
    )


def test_mixed_catalog_factory_is_rejected_before_path_construction() -> None:
    from pa_agent.research_backtest.simulation.context import (
        RunConfigurationMismatch,
        build_production_engine_dependencies,
        make_production_run_context,
        validate_production_engine_dependencies,
    )
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
        production_maintenance_evidence_factory,
    )

    inputs, config, catalog, execution = _production_case()
    context = make_production_run_context(
        inputs=inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id="f" * 64,
    )
    dependencies = build_production_engine_dependencies(context)
    foreign = make_simulation_evidence_catalog(
        target_opens=catalog.target_opens,
        watermarks=catalog.watermarks,
        contracts=catalog.contracts,
        costs=catalog.costs,
        funding_schedules=catalog.funding_schedules,
        funding_risks=catalog.funding_risks,
        maintenance=catalog.maintenance,
        stage=catalog.stage,
        split_start_utc_ms=catalog.split_start_utc_ms,
        split_end_utc_ms=catalog.split_end_utc_ms + 60_000,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )
    mismatched = replace(
        dependencies,
        maintenance_evidence_factory=production_maintenance_evidence_factory(foreign),
    )
    with pytest.raises(RunConfigurationMismatch, match="factory Catalog"):
        validate_production_engine_dependencies(context, mismatched)
