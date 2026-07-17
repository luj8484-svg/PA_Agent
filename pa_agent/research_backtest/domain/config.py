from __future__ import annotations

from dataclasses import dataclass

from pa_agent.research_backtest.domain.base import formal_identity, verify_formal_identity
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.versions import CANONICAL_2B_VERSION, EXECUTION_TIME_CONFIG_VERSION


@dataclass(frozen=True, slots=True)
class ExecutionTimeConfig:
    schema_version: str
    config_id: str
    config_content_hash: str
    entry_delay_minutes: int
    exit_delay_minutes: int
    anchor_policy_version: str
    version: str
    canonical_version: str

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_TIME_CONFIG_VERSION:
            raise ValueError("unsupported ExecutionTimeConfig schema version")
        if self.version != EXECUTION_TIME_CONFIG_VERSION:
            raise ValueError("unsupported execution-time version")
        if self.canonical_version != CANONICAL_2B_VERSION:
            raise ValueError("unsupported 2B Canonical version")
        if type(self.entry_delay_minutes) is not int or self.entry_delay_minutes not in {0, 1, 2}:
            raise ValueError("entry delay must be 0, 1, or 2 minutes")
        if type(self.exit_delay_minutes) is not int or self.exit_delay_minutes not in {0, 1, 2}:
            raise ValueError("exit delay must be 0, 1, or 2 minutes")
        if not isinstance(self.anchor_policy_version, str) or not self.anchor_policy_version:
            raise ValueError("anchor policy version must be nonempty")
        verify_formal_identity(
            self,
            id_field="config_id",
            hash_field="config_content_hash",
            prefix="etime_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def execution_time_config(
    *,
    entry_delay_minutes: int,
    exit_delay_minutes: int,
    anchor_policy_version: str = "NEXT_4H_OPEN_AFTER_CLOSED_BAR_V1",
) -> ExecutionTimeConfig:
    payload = {
        "schema_version": EXECUTION_TIME_CONFIG_VERSION,
        "entry_delay_minutes": entry_delay_minutes,
        "exit_delay_minutes": exit_delay_minutes,
        "anchor_policy_version": anchor_policy_version,
        "version": EXECUTION_TIME_CONFIG_VERSION,
        "canonical_version": CANONICAL_2B_VERSION,
    }
    config_id, digest = formal_identity("etime_", payload)
    return ExecutionTimeConfig(config_id=config_id, config_content_hash=digest, **payload)
