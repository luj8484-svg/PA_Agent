from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import ScheduledExitReason, Side
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    ENTRY_INTENT_SCHEMA_VERSION,
    EXECUTION_TIME_CONFIG_VERSION,
    EXIT_CONDITION_SNAPSHOT_VERSION,
    EXIT_INTENT_SCHEMA_VERSION,
    STRATEGY_CANDIDATE_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class EntryIntent:
    schema_version: str
    intent_id: str
    intent_content_hash: str
    candidate_id: str
    candidate_schema_version: str
    computational_experiment_id: str
    symbol: str
    side: Side
    candidate_decision_time_utc_ms: int
    intent_created_time_utc_ms: int
    execution_anchor_utc_ms: int
    target_execution_time_utc_ms: int
    execution_delay_minutes: int
    execution_time_config_id: str
    execution_time_config_content_hash: str
    execution_time_config_version: str
    decision_visible_input_hash: str
    strategy_version: str
    intent_config_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != ENTRY_INTENT_SCHEMA_VERSION:
            raise ValueError("unsupported EntryIntent schema version")
        if self.candidate_schema_version != STRATEGY_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported Candidate schema version")
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.side, Side):
            raise ValueError("invalid EntryIntent market identity")
        for name in (
            "candidate_decision_time_utc_ms",
            "intent_created_time_utc_ms",
            "execution_anchor_utc_ms",
            "target_execution_time_utc_ms",
        ):
            require_utc_ms(getattr(self, name), name)
        if self.intent_created_time_utc_ms != self.candidate_decision_time_utc_ms:
            raise ValueError("Intent creation time must equal Candidate decision time")
        if (self.candidate_decision_time_utc_ms + 1) % 14_400_000 != 0:
            raise ValueError("Candidate decision time must be an exact 4H close")
        if self.execution_anchor_utc_ms != self.candidate_decision_time_utc_ms + 1:
            raise ValueError("execution anchor must be the next 4H UTC open")
        if type(self.execution_delay_minutes) is not int or self.execution_delay_minutes not in {
            0,
            1,
            2,
        }:
            raise ValueError("unsupported execution delay")
        if self.target_execution_time_utc_ms != (
            self.execution_anchor_utc_ms + self.execution_delay_minutes * 60_000
        ):
            raise ValueError("target execution time contradicts the frozen delay")
        if self.execution_time_config_version != EXECUTION_TIME_CONFIG_VERSION:
            raise ValueError("unsupported execution-time config version")
        for name in (
            "computational_experiment_id",
            "execution_time_config_content_hash",
            "decision_visible_input_hash",
            "intent_config_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        require_commit(self.code_commit)
        expected_config_hash = canonical_sha256(
            {
                "execution_time_config_id": self.execution_time_config_id,
                "execution_time_config_content_hash": self.execution_time_config_content_hash,
                "entry_intent_schema_version": ENTRY_INTENT_SCHEMA_VERSION,
                "canonical_version": CANONICAL_2B_VERSION,
            }
        )
        if self.intent_config_hash != expected_config_hash:
            raise ValueError("intent config hash does not match frozen inputs")
        verify_formal_identity(
            self,
            id_field="intent_id",
            hash_field="intent_content_hash",
            prefix="eint_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class ExitConditionSnapshot:
    schema_version: str
    condition_event_id: str
    condition_content_hash: str
    origin_candidate_id: str
    position_id: str
    position_snapshot_hash: str
    symbol: str
    position_side: Side
    exit_quantity: Decimal
    scheduled_exit_reason: ScheduledExitReason
    condition_time_utc_ms: int
    condition_visible_input_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != EXIT_CONDITION_SNAPSHOT_VERSION:
            raise ValueError("unsupported exit-condition snapshot schema")
        for name in ("origin_candidate_id", "position_id"):
            require_nonempty_string(getattr(self, name), name)
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.position_side, Side):
            raise ValueError("invalid exit-condition market identity")
        if (
            not isinstance(self.exit_quantity, Decimal)
            or not self.exit_quantity.is_finite()
            or self.exit_quantity <= 0
        ):
            raise ValueError("exit quantity must be finite positive Decimal")
        if not isinstance(self.scheduled_exit_reason, ScheduledExitReason):
            raise ValueError("protective exits cannot enter scheduled exit planning")
        require_utc_ms(self.condition_time_utc_ms, "condition_time_utc_ms")
        for name in (
            "position_snapshot_hash",
            "condition_visible_input_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        require_commit(self.code_commit)
        verify_formal_identity(
            self,
            id_field="condition_event_id",
            hash_field="condition_content_hash",
            prefix="xcond_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class ExitIntent:
    schema_version: str
    intent_id: str
    intent_content_hash: str
    condition_event_id: str
    origin_candidate_id: str
    position_id: str
    position_snapshot_hash: str
    symbol: str
    position_side: Side
    full_exit_quantity: Decimal
    scheduled_exit_reason: ScheduledExitReason
    condition_visible_input_hash: str
    computational_experiment_id: str
    condition_time_utc_ms: int
    intent_created_time_utc_ms: int
    execution_anchor_utc_ms: int
    target_execution_time_utc_ms: int
    execution_delay_minutes: int
    execution_time_config_id: str
    execution_time_config_content_hash: str
    execution_time_config_version: str
    intent_config_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != EXIT_INTENT_SCHEMA_VERSION:
            raise ValueError("unsupported ExitIntent schema")
        for name in ("condition_event_id", "origin_candidate_id", "position_id"):
            require_nonempty_string(getattr(self, name), name)
        if self.symbol not in {"BTCUSDT", "ETHUSDT"} or not isinstance(self.position_side, Side):
            raise ValueError("invalid ExitIntent market identity")
        if (
            not isinstance(self.full_exit_quantity, Decimal)
            or not self.full_exit_quantity.is_finite()
            or self.full_exit_quantity <= 0
        ):
            raise ValueError("full exit quantity must be finite positive Decimal")
        if not isinstance(self.scheduled_exit_reason, ScheduledExitReason):
            raise ValueError("ExitIntent only accepts scheduled exit reasons")
        for name in (
            "condition_time_utc_ms",
            "intent_created_time_utc_ms",
            "execution_anchor_utc_ms",
            "target_execution_time_utc_ms",
        ):
            require_utc_ms(getattr(self, name), name)
        if self.intent_created_time_utc_ms != self.condition_time_utc_ms:
            raise ValueError("ExitIntent creation time must equal condition time")
        expected_anchor = (self.condition_time_utc_ms // 60_000) * 60_000 + 60_000
        if self.execution_anchor_utc_ms != expected_anchor:
            raise ValueError("exit execution anchor must be the next minute open")
        if type(self.execution_delay_minutes) is not int or self.execution_delay_minutes not in {
            0,
            1,
            2,
        }:
            raise ValueError("unsupported exit execution delay")
        if self.target_execution_time_utc_ms != (
            expected_anchor + self.execution_delay_minutes * 60_000
        ):
            raise ValueError("exit target contradicts the frozen delay")
        if self.target_execution_time_utc_ms <= self.condition_time_utc_ms:
            raise ValueError("exit target must be strictly after condition time")
        if self.execution_time_config_version != EXECUTION_TIME_CONFIG_VERSION:
            raise ValueError("unsupported execution-time config version")
        for name in (
            "position_snapshot_hash",
            "condition_visible_input_hash",
            "computational_experiment_id",
            "execution_time_config_content_hash",
            "intent_config_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        expected_config = canonical_sha256(
            {
                "execution_time_config_id": self.execution_time_config_id,
                "execution_time_config_content_hash": (self.execution_time_config_content_hash),
                "exit_intent_schema_version": EXIT_INTENT_SCHEMA_VERSION,
                "canonical_version": CANONICAL_2B_VERSION,
            }
        )
        if self.intent_config_hash != expected_config:
            raise ValueError("exit intent config hash does not match frozen inputs")
        require_commit(self.code_commit)
        verify_formal_identity(
            self, id_field="intent_id", hash_field="intent_content_hash", prefix="xint_"
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def exit_condition_snapshot(**values: object) -> ExitConditionSnapshot:
    payload = {"schema_version": EXIT_CONDITION_SNAPSHOT_VERSION, **values}
    condition_id, digest = formal_identity("xcond_", payload)
    return ExitConditionSnapshot(
        condition_event_id=condition_id, condition_content_hash=digest, **payload
    )


def exit_intent(payload: dict[str, object]) -> ExitIntent:
    intent_id, digest = formal_identity("xint_", payload)
    return ExitIntent(intent_id=intent_id, intent_content_hash=digest, **payload)
