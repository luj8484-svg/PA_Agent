from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

HASH = "a" * 64
COMMIT = "b" * 40


def config_payload() -> dict[str, object]:
    return {
        "symbols": ("BTCUSDT", "ETHUSDT"),
        "simulation_start_utc_ms": 0,
        "simulation_end_exit_open_utc_ms": 120_000,
        "initial_wallet_balance": Decimal("10000"),
        "cost_model_version": "COST_V1",
        "funding_model_version": "FUNDING_V1",
        "two_a_version": "2A_V1",
        "two_b_planner_version": "2B_V1",
        "two_b_planner_config_hash": HASH,
        "code_commit": COMMIT,
        "dependency_lock_hash": HASH,
    }


def test_simulation_config_is_closed_and_content_addressed() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    first = make_simulation_config(**config_payload())
    second = make_simulation_config(**config_payload())
    assert first == second
    assert first.config_id.startswith("simcfg_")
    assert len(first.config_content_hash) == 64
    assert first.schema_version == "SIMULATION_CONFIG_V1"


@pytest.mark.parametrize("field", ["simulation_start_utc_ms", "simulation_end_exit_open_utc_ms"])
def test_simulation_config_rejects_non_minute_boundaries(field: str) -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    payload = config_payload()
    payload[field] = 1
    with pytest.raises(ValueError, match="UTC one-minute"):
        make_simulation_config(**payload)


def test_simulation_config_rejects_float_money() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    with pytest.raises(ValueError, match="Decimal"):
        make_simulation_config(**(config_payload() | {"initial_wallet_balance": 10000.0}))


def test_initial_state_is_frozen() -> None:
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )

    state = initial_engine_state(make_simulation_config(**config_payload()))
    assert state.wallet_balance == Decimal("10000")
    assert state.equity == state.peak_equity == Decimal("10000")
    assert state.locked_initial_margin == Decimal("0")
    assert state.locked_fee_reserve == Decimal("0")
    assert state.locked_funding_reserve == Decimal("0")
    assert state.pending_plan_reserve == Decimal("0")
    assert state.positions == ()
    assert state.path_state.value == "VALID"


def test_config_tamper_is_detected() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    config = make_simulation_config(**config_payload())
    with pytest.raises(ValueError, match="Canonical content"):
        replace(config, initial_wallet_balance=Decimal("9999"))


def test_run_identity_excludes_acquisition_and_prefabricated_plans() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.identity import (
        make_simulation_input_identity,
        simulation_run_id,
    )

    config = make_simulation_config(**config_payload())
    identity = make_simulation_input_identity(
        trade_content_hash=HASH,
        mark_content_hash="b" * 64,
        funding_content_hash="c" * 64,
        candidate_content_hash="d" * 64,
        contract_content_hash="e" * 64,
        cost_content_hash="f" * 64,
        funding_risk_content_hash="1" * 64,
        maintenance_content_hash="2" * 64,
    )
    assert simulation_run_id(identity, config) == simulation_run_id(identity, config)
    assert not hasattr(identity, "acquisition_manifest_hash")
    assert not hasattr(identity, "entry_plans")


@pytest.mark.parametrize(
    "changed_field",
    [
        "trade_content_hash",
        "mark_content_hash",
        "funding_content_hash",
        "candidate_content_hash",
        "contract_content_hash",
        "cost_content_hash",
        "funding_risk_content_hash",
        "maintenance_content_hash",
    ],
)
def test_every_material_input_component_changes_run_identity(changed_field: str) -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.identity import (
        make_simulation_input_identity,
        simulation_run_id,
    )

    config = make_simulation_config(**config_payload())
    components = {
        "trade_content_hash": "1" * 64,
        "mark_content_hash": "2" * 64,
        "funding_content_hash": "3" * 64,
        "candidate_content_hash": "4" * 64,
        "contract_content_hash": "5" * 64,
        "cost_content_hash": "6" * 64,
        "funding_risk_content_hash": "7" * 64,
        "maintenance_content_hash": "8" * 64,
    }
    baseline = make_simulation_input_identity(**components)
    changed = make_simulation_input_identity(**(components | {changed_field: "9" * 64}))
    assert simulation_run_id(baseline, config) != simulation_run_id(changed, config)


def test_input_identity_is_built_from_actual_inputs_and_catalog() -> None:
    from pa_agent.research_backtest.simulation.evidence import (
        make_simulation_evidence_catalog,
    )
    from pa_agent.research_backtest.simulation.identity import (
        build_simulation_input_identity,
        verify_simulation_input_identity,
    )
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs
    from tests.research_backtest.simulation.test_minute_engine_output import minute

    entry = complete_entry_inputs()
    inputs = SimulationInputs((minute(60_000),), (entry.candidate,), ())
    catalog = make_simulation_evidence_catalog(
        target_opens=(entry.target_open,),
        watermarks=(entry.watermark,),
        contracts=(entry.contract,),
        costs=(entry.cost,),
        funding_schedules=(entry.funding_schedule,),
        funding_risks=(entry.funding_risk,),
        maintenance=(),
        stage=entry.stage,
        split_start_utc_ms=entry.split_start_utc_ms,
        split_end_utc_ms=entry.split_end_utc_ms,
        code_commit=entry.code_commit,
        dependency_lock_hash=entry.dependency_lock_hash,
    )
    identity = build_simulation_input_identity(inputs, catalog)
    verify_simulation_input_identity(identity, inputs, catalog)
    assert identity.input_identity_id.startswith("siminput_")
    assert len(identity.input_identity_content_hash) == 64


def test_actual_stream_change_changes_input_and_run_identity() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import empty_simulation_evidence_catalog
    from pa_agent.research_backtest.simulation.identity import (
        build_simulation_input_identity,
        simulation_run_id,
    )
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from tests.research_backtest.simulation.test_minute_engine_output import minute

    config = make_simulation_config(**config_payload())
    inputs = SimulationInputs((minute(60_000),), (), ())
    changed_minute = replace(
        minute(60_000),
        trade_bars=(replace(minute(60_000).trade_bars[0], content_hash="f" * 64),),
    )
    changed = SimulationInputs((changed_minute,), (), ())
    catalog = empty_simulation_evidence_catalog(config)
    left = build_simulation_input_identity(inputs, catalog)
    right = build_simulation_input_identity(changed, catalog)
    assert left.input_identity_content_hash != right.input_identity_content_hash
    assert simulation_run_id(left, config) != simulation_run_id(right, config)


def test_tampered_external_identity_fails_closed() -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config
    from pa_agent.research_backtest.simulation.evidence import empty_simulation_evidence_catalog
    from pa_agent.research_backtest.simulation.identity import (
        build_simulation_input_identity,
        verify_simulation_input_identity,
    )
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from tests.research_backtest.simulation.test_minute_engine_output import minute

    config = make_simulation_config(**config_payload())
    inputs = SimulationInputs((minute(60_000),), (), ())
    catalog = empty_simulation_evidence_catalog(config)
    identity = build_simulation_input_identity(inputs, catalog)
    with pytest.raises(ValueError, match="identity does not match actual simulation inputs"):
        verify_simulation_input_identity(
            identity,
            SimulationInputs(
                (replace(minute(60_000), mark_bars=()),),
                (),
                (),
            ),
            catalog,
        )


def test_canonical_rejects_binary_float() -> None:
    from pa_agent.research_backtest.simulation.identity import canonical_2c_sha256

    with pytest.raises(TypeError, match="Binary floats"):
        canonical_2c_sha256({"price": 1.25})


def test_event_order_and_models_are_frozen() -> None:
    from pa_agent.research_backtest.simulation.versions import (
        EVENT_STAGES,
        LIQUIDATION_MODEL_VERSION,
    )

    assert len(EVENT_STAGES) == 14
    assert EVENT_STAGES[4] == "OPEN_GAP_PROTECTIVE_GATE"
    assert EVENT_STAGES[5] == "SCHEDULED_OPEN_EXITS"
    assert LIQUIDATION_MODEL_VERSION == "ESTIMATED_FIXED_ISOLATED_MARGIN_V1"


def test_scope_guard_has_no_forbidden_capability() -> None:
    from pathlib import Path

    from pa_agent.research_backtest.simulation.scope_guard import scan_simulation_scope

    root = Path(__file__).parents[3] / "pa_agent" / "research_backtest" / "simulation"
    assert scan_simulation_scope(root) == ()
