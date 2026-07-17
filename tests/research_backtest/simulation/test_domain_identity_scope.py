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
    from pa_agent.research_backtest.simulation.domain import initial_engine_state
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

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
    from pa_agent.research_backtest.simulation.identity import SimulationInputIdentity
    from pa_agent.research_backtest.simulation.identity import simulation_run_id

    config = make_simulation_config(**config_payload())
    identity = SimulationInputIdentity(
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


def test_canonical_rejects_binary_float() -> None:
    from pa_agent.research_backtest.simulation.identity import canonical_2c_sha256

    with pytest.raises(TypeError, match="Binary floats"):
        canonical_2c_sha256({"price": 1.25})


def test_event_order_and_models_are_frozen() -> None:
    from pa_agent.research_backtest.simulation.versions import EVENT_STAGES
    from pa_agent.research_backtest.simulation.versions import LIQUIDATION_MODEL_VERSION

    assert len(EVENT_STAGES) == 14
    assert EVENT_STAGES[4] == "OPEN_GAP_PROTECTIVE_GATE"
    assert EVENT_STAGES[5] == "SCHEDULED_OPEN_EXITS"
    assert LIQUIDATION_MODEL_VERSION == "ESTIMATED_FIXED_ISOLATED_MARGIN_V1"


def test_scope_guard_has_no_forbidden_capability() -> None:
    from pathlib import Path

    from pa_agent.research_backtest.simulation.scope_guard import scan_simulation_scope

    root = Path(__file__).parents[3] / "pa_agent" / "research_backtest" / "simulation"
    assert scan_simulation_scope(root) == ()
