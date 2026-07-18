from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_sha256,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.simulation.domain import SimulationConfig
from pa_agent.research_backtest.simulation.evidence import SimulationEvidenceCatalog
from pa_agent.research_backtest.simulation.inputs import SimulationInputs

SIMULATION_INPUT_IDENTITY_VERSION = "SIMULATION_INPUT_IDENTITY_V1"


@dataclass(frozen=True, slots=True)
class SimulationInputIdentity:
    schema_version: str
    input_identity_id: str
    input_identity_content_hash: str
    simulation_inputs_content_hash: str
    trade_content_hash: str
    mark_content_hash: str
    funding_content_hash: str
    candidate_content_hash: str
    contract_content_hash: str
    cost_content_hash: str
    funding_risk_content_hash: str
    maintenance_content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != SIMULATION_INPUT_IDENTITY_VERSION:
            raise ValueError("unsupported simulation input identity")
        for name in self.__dataclass_fields__:
            if name.endswith("_hash"):
                require_sha256(getattr(self, name), name)
        verify_formal_identity(
            self,
            id_field="input_identity_id",
            hash_field="input_identity_content_hash",
            prefix="siminput_",
        )


def make_simulation_input_identity(
    *,
    trade_content_hash: str,
    mark_content_hash: str,
    funding_content_hash: str,
    candidate_content_hash: str,
    contract_content_hash: str,
    cost_content_hash: str,
    funding_risk_content_hash: str,
    maintenance_content_hash: str,
    simulation_inputs_content_hash: str | None = None,
) -> SimulationInputIdentity:
    components = {
        "trade_content_hash": trade_content_hash,
        "mark_content_hash": mark_content_hash,
        "funding_content_hash": funding_content_hash,
        "candidate_content_hash": candidate_content_hash,
        "contract_content_hash": contract_content_hash,
        "cost_content_hash": cost_content_hash,
        "funding_risk_content_hash": funding_risk_content_hash,
        "maintenance_content_hash": maintenance_content_hash,
    }
    payload = {
        "schema_version": SIMULATION_INPUT_IDENTITY_VERSION,
        "simulation_inputs_content_hash": simulation_inputs_content_hash
        or canonical_sha256(components),
        **components,
    }
    object_id, digest = formal_identity("siminput_", payload)
    return SimulationInputIdentity(
        input_identity_id=object_id,
        input_identity_content_hash=digest,
        **payload,
    )


def build_simulation_input_identity(
    inputs: SimulationInputs,
    catalog: SimulationEvidenceCatalog,
) -> SimulationInputIdentity:
    trade = tuple(bar for minute in inputs.minute_slices for bar in minute.trade_bars)
    mark = tuple(bar for minute in inputs.minute_slices for bar in minute.mark_bars)
    funding = tuple(record for minute in inputs.minute_slices for record in minute.funding_records)
    return make_simulation_input_identity(
        simulation_inputs_content_hash=canonical_sha256(
            {"minute_slices": inputs.minute_slices, "candidates": inputs.candidates}
        ),
        trade_content_hash=canonical_sha256(trade),
        mark_content_hash=canonical_sha256(mark),
        funding_content_hash=canonical_sha256(funding),
        candidate_content_hash=canonical_sha256(inputs.candidates),
        contract_content_hash=canonical_sha256(catalog.contracts),
        cost_content_hash=canonical_sha256(catalog.costs),
        funding_risk_content_hash=canonical_sha256(
            {"schedules": catalog.funding_schedules, "risks": catalog.funding_risks}
        ),
        maintenance_content_hash=canonical_sha256(catalog.maintenance),
    )


def verify_simulation_input_identity(
    identity: SimulationInputIdentity,
    inputs: SimulationInputs,
    catalog: SimulationEvidenceCatalog,
) -> None:
    expected = build_simulation_input_identity(inputs, catalog)
    if identity != expected:
        raise ValueError("identity does not match actual simulation inputs and evidence catalog")


def canonical_2c_sha256(value: object) -> str:
    return canonical_sha256(value)


def simulation_run_id(identity: SimulationInputIdentity, config: SimulationConfig) -> str:
    return (
        "simrun_"
        + canonical_sha256(
            {
                "input_identity_hash": identity.input_identity_content_hash,
                "simulation_config_hash": config.config_content_hash,
            }
        )[:32]
    )
