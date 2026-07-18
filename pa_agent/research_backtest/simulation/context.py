from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import ExecutionTimeConfig
from pa_agent.research_backtest.domain.enums import ResearchStage
from pa_agent.research_backtest.simulation.domain import SimulationConfig
from pa_agent.research_backtest.simulation.evidence import SimulationEvidenceCatalog
from pa_agent.research_backtest.simulation.identity import (
    SimulationInputIdentity,
    build_simulation_input_identity,
    verify_simulation_input_identity,
)
from pa_agent.research_backtest.simulation.inputs import SimulationInputs
from pa_agent.research_backtest.simulation.versions import MINUTE_ENGINE_VERSION
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    INDICATOR_CONFIG_VERSION,
)


class RunConfigurationMismatch(ValueError):
    """Production identities do not describe the objects that would execute."""


@dataclass(frozen=True, slots=True)
class ProductionRunContext:
    config: SimulationConfig
    evidence_catalog: SimulationEvidenceCatalog
    candidates: tuple[object, ...]
    execution_time_config: ExecutionTimeConfig
    computational_experiment_id: str
    stage: ResearchStage
    split_start_utc_ms: int
    split_end_utc_ms: int
    code_commit: str
    dependency_lock_hash: str
    input_identity: SimulationInputIdentity
    planner_identity_content_hash: str
    two_a_identity_content_hash: str
    two_b_identity_content_hash: str
    two_c_identity_content_hash: str

    def __post_init__(self) -> None:
        validate_production_run_context(self)


def _identity_hash(name: str, version: str, config: SimulationConfig) -> str:
    return canonical_sha256(
        {
            "name": name,
            "version": version,
            "code_commit": config.code_commit,
            "dependency_lock_hash": config.dependency_lock_hash,
        }
    )


def _validate_config(
    config: SimulationConfig,
    catalog: SimulationEvidenceCatalog,
    execution: ExecutionTimeConfig,
) -> None:
    if config.code_commit != catalog.code_commit:
        raise RunConfigurationMismatch("Config/Catalog code identity mismatch")
    if config.dependency_lock_hash != catalog.dependency_lock_hash:
        raise RunConfigurationMismatch("Config/Catalog dependency identity mismatch")
    if config.two_b_planner_config_hash != execution.config_content_hash:
        raise RunConfigurationMismatch("ExecutionTimeConfig does not match 2B planner config")
    if config.two_a_version != INDICATOR_CONFIG_VERSION:
        raise RunConfigurationMismatch("actual 2A identity/version mismatch")
    if config.two_b_planner_version != CANONICAL_2B_VERSION:
        raise RunConfigurationMismatch("actual 2B planner identity/version mismatch")
    if config.two_c_engine_version != MINUTE_ENGINE_VERSION:
        raise RunConfigurationMismatch("actual 2C engine identity/version mismatch")
    if (
        catalog.split_start_utc_ms > config.simulation_start_utc_ms
        or catalog.split_end_utc_ms < config.simulation_end_exit_open_utc_ms
    ):
        raise RunConfigurationMismatch("Catalog split does not cover SimulationConfig interval")


def make_production_run_context(
    *,
    inputs: SimulationInputs,
    config: SimulationConfig,
    evidence_catalog: SimulationEvidenceCatalog,
    execution_time_config: ExecutionTimeConfig,
    computational_experiment_id: str,
) -> ProductionRunContext:
    _validate_config(config, evidence_catalog, execution_time_config)
    if inputs.candidates and not any(
        (
            evidence_catalog.target_opens,
            evidence_catalog.watermarks,
            evidence_catalog.contracts,
            evidence_catalog.costs,
            evidence_catalog.funding_schedules,
            evidence_catalog.funding_risks,
        )
    ):
        raise RunConfigurationMismatch("Candidate stream cannot use an empty evidence Catalog")
    planner_hash = canonical_sha256(
        {
            "planner": "POSITION_SIZING_BATCH_SCALING_ENTRY_EXIT_V1",
            "version": config.two_b_planner_version,
            "execution_time_config_hash": execution_time_config.config_content_hash,
            "catalog_id": evidence_catalog.catalog_id,
            "catalog_content_hash": evidence_catalog.catalog_content_hash,
        }
    )
    two_a_hash = _identity_hash("2A", config.two_a_version, config)
    two_b_hash = _identity_hash("2B", config.two_b_planner_version, config)
    two_c_hash = _identity_hash("2C", config.two_c_engine_version, config)
    identity = build_simulation_input_identity(
        inputs,
        evidence_catalog,
        execution_time_config=execution_time_config,
        planner_identity_content_hash=planner_hash,
        two_a_identity_content_hash=two_a_hash,
        two_b_identity_content_hash=two_b_hash,
        two_c_identity_content_hash=two_c_hash,
    )
    return ProductionRunContext(
        config=config,
        evidence_catalog=evidence_catalog,
        candidates=inputs.candidates,
        execution_time_config=execution_time_config,
        computational_experiment_id=computational_experiment_id,
        stage=evidence_catalog.stage,
        split_start_utc_ms=evidence_catalog.split_start_utc_ms,
        split_end_utc_ms=evidence_catalog.split_end_utc_ms,
        code_commit=evidence_catalog.code_commit,
        dependency_lock_hash=evidence_catalog.dependency_lock_hash,
        input_identity=identity,
        planner_identity_content_hash=planner_hash,
        two_a_identity_content_hash=two_a_hash,
        two_b_identity_content_hash=two_b_hash,
        two_c_identity_content_hash=two_c_hash,
    )


def validate_production_run_context(
    context: ProductionRunContext,
    inputs: SimulationInputs | None = None,
) -> None:
    _validate_config(
        context.config,
        context.evidence_catalog,
        context.execution_time_config,
    )
    identity = context.input_identity
    catalog = context.evidence_catalog
    if (
        context.stage != catalog.stage
        or context.split_start_utc_ms != catalog.split_start_utc_ms
        or context.split_end_utc_ms != catalog.split_end_utc_ms
        or context.code_commit != catalog.code_commit
        or context.dependency_lock_hash != catalog.dependency_lock_hash
    ):
        raise RunConfigurationMismatch("Run Context declaration differs from Catalog")
    if (
        identity.evidence_catalog_id != catalog.catalog_id
        or identity.evidence_catalog_content_hash != catalog.catalog_content_hash
    ):
        raise RunConfigurationMismatch("Run Identity uses a different evidence Catalog")
    if identity.candidate_content_hash != canonical_sha256(context.candidates):
        raise RunConfigurationMismatch("Candidate manifest differs from Run Identity")
    expected_pairs = (
        (identity.target_open_content_hash, canonical_sha256(catalog.target_opens)),
        (identity.watermark_content_hash, canonical_sha256(catalog.watermarks)),
        (
            identity.execution_time_config_content_hash,
            context.execution_time_config.config_content_hash,
        ),
        (identity.planner_identity_content_hash, context.planner_identity_content_hash),
        (identity.two_a_identity_content_hash, context.two_a_identity_content_hash),
        (identity.two_b_identity_content_hash, context.two_b_identity_content_hash),
        (identity.two_c_identity_content_hash, context.two_c_identity_content_hash),
    )
    if any(actual != expected for actual, expected in expected_pairs):
        raise RunConfigurationMismatch("Run Context actual identity mismatch")
    if inputs is not None:
        if inputs.candidates != context.candidates:
            raise RunConfigurationMismatch("Candidate stream differs from ProductionRunContext")
        try:
            verify_simulation_input_identity(
                identity,
                inputs,
                catalog,
                execution_time_config=context.execution_time_config,
                planner_identity_content_hash=context.planner_identity_content_hash,
                two_a_identity_content_hash=context.two_a_identity_content_hash,
                two_b_identity_content_hash=context.two_b_identity_content_hash,
                two_c_identity_content_hash=context.two_c_identity_content_hash,
            )
        except ValueError as exc:
            raise RunConfigurationMismatch(
                "Run Identity does not match actual production inputs"
            ) from exc


def build_production_engine_dependencies(context: ProductionRunContext):
    from pa_agent.research_backtest.simulation.engine import EngineDependencies
    from pa_agent.research_backtest.simulation.evidence import (
        production_execution_cost_factory,
        production_maintenance_evidence_factory,
        production_planning_evidence_factory,
    )
    from pa_agent.research_backtest.simulation.planning import (
        make_candidate_intent_factory,
        make_scheduled_exit_intent_factory,
        production_planner_dependencies,
    )

    validate_production_run_context(context)
    catalog = context.evidence_catalog
    planners = production_planner_dependencies(catalog, context.candidates)
    entry_intent_factory = make_candidate_intent_factory(
        context.execution_time_config,
        computational_experiment_id=context.computational_experiment_id,
        stage=catalog.stage,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )
    exit_intent_factory = make_scheduled_exit_intent_factory(
        context.execution_time_config,
        computational_experiment_id=context.computational_experiment_id,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )
    for factory in (entry_intent_factory, exit_intent_factory):
        factory.catalog_id = catalog.catalog_id  # type: ignore[attr-defined]
        factory.catalog_content_hash = catalog.catalog_content_hash  # type: ignore[attr-defined]
    planning_factory = production_planning_evidence_factory(catalog)
    maintenance_factory = production_maintenance_evidence_factory(catalog)
    cost_factory = production_execution_cost_factory(catalog)
    dependencies = EngineDependencies(
        planners=planners,
        entry_intent_factory=entry_intent_factory,
        exit_intent_factory=exit_intent_factory,
        planning_evidence_factory=planning_factory,
        maintenance_evidence_factory=maintenance_factory,
        execution_cost_factory=cost_factory,
        evidence_catalog=catalog,
        catalog_id=catalog.catalog_id,
        catalog_content_hash=catalog.catalog_content_hash,
    )
    validate_production_engine_dependencies(context, dependencies)
    return dependencies


def validate_production_engine_dependencies(
    context: ProductionRunContext,
    dependencies: object,
) -> None:
    catalog = context.evidence_catalog
    bound = (
        dependencies.planners,
        dependencies.entry_intent_factory,
        dependencies.exit_intent_factory,
        dependencies.planning_evidence_factory,
        dependencies.maintenance_evidence_factory,
        dependencies.execution_cost_factory,
    )
    if any(
        getattr(item, "catalog_id", None) != catalog.catalog_id
        or getattr(item, "catalog_content_hash", None) != catalog.catalog_content_hash
        for item in bound
    ):
        raise RunConfigurationMismatch("Production factory Catalog binding mismatch")


def run_production_simulation(inputs: SimulationInputs, context: ProductionRunContext):
    from pa_agent.research_backtest.simulation.engine import run_simulation

    validate_production_run_context(context, inputs)
    return run_simulation(
        inputs,
        context.config,
        build_production_engine_dependencies(context),
        context.input_identity,
    )
