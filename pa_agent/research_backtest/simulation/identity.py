from dataclasses import dataclass

from pa_agent.research_backtest.domain.base import require_sha256
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.simulation.domain import SimulationConfig


@dataclass(frozen=True, slots=True)
class SimulationInputIdentity:
    trade_content_hash: str
    mark_content_hash: str
    funding_content_hash: str
    candidate_content_hash: str
    contract_content_hash: str
    cost_content_hash: str
    funding_risk_content_hash: str
    maintenance_content_hash: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            require_sha256(getattr(self, name), name)


def canonical_2c_sha256(value: object) -> str:
    return canonical_sha256(value)


def simulation_run_id(identity: SimulationInputIdentity, config: SimulationConfig) -> str:
    return (
        "simrun_"
        + canonical_sha256(
            {"input_identity": identity, "simulation_config_hash": config.config_content_hash}
        )[:32]
    )
