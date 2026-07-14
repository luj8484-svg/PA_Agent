from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import ValidationReason
from pa_agent.research_backtest.versions import VALIDATION_FAILURE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ValidationFailure:
    schema_version: str
    failure_id: str
    reason: ValidationReason
    symbol: str
    decision_time_utc_ms: int
    affected_interval: str
    decision_visible_input_hash: str | None
    expected_values: tuple[tuple[str, str], ...]
    observed_values: tuple[tuple[str, str], ...]
    gap_intervals: tuple[tuple[int, int], ...]
    indicator_config_hash: str
    code_commit: str
    dependency_lock_hash: str
    created_by: str

    def __post_init__(self) -> None:
        if self.schema_version != VALIDATION_FAILURE_SCHEMA_VERSION:
            raise ValueError("unsupported ValidationFailure schema version")
        if not isinstance(self.reason, ValidationReason):
            raise ValueError("failure reason must use the frozen enum")
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("failure symbol must be nonempty")
        if type(self.decision_time_utc_ms) is not int:
            raise ValueError("failure decision time must be integer UTC milliseconds")
        if self.affected_interval not in {"1d", "4h", "1d/4h"}:
            raise ValueError("failure affected interval is unsupported")
        if self.created_by != "PYTHON_DETERMINISTIC":
            raise ValueError("failure must be created by deterministic Python")
        if (
            self.decision_visible_input_hash is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.decision_visible_input_hash) is None
        ):
            raise ValueError("decision-visible input hash must be lowercase SHA-256")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.indicator_config_hash, self.dependency_lock_hash)
        ):
            raise ValueError("failure SHA-256 fields must be 64 lowercase hex characters")
        if re.fullmatch(r"[0-9a-f]{7,64}", self.code_commit) is None:
            raise ValueError("code_commit must be a lowercase hexadecimal commit identity")
        for evidence in (self.expected_values, self.observed_values):
            if not isinstance(evidence, tuple) or evidence != tuple(sorted(evidence)):
                raise ValueError("failure evidence must be canonically sorted tuples")
            if any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                for item in evidence
            ):
                raise ValueError("failure evidence must contain string key/value pairs")
        if not isinstance(self.gap_intervals, tuple) or self.gap_intervals != tuple(
            sorted(self.gap_intervals)
        ):
            raise ValueError("gap intervals must be canonically sorted tuples")
        if any(
            not isinstance(interval, tuple)
            or len(interval) != 2
            or any(type(value) is not int for value in interval)
            or interval[0] > interval[1]
            for interval in self.gap_intervals
        ):
            raise ValueError("gap intervals must contain ordered integer boundaries")
        if re.fullmatch(r"val_[0-9a-f]{24}", self.failure_id) is None:
            raise ValueError("failure_id has an invalid format")
        payload = asdict(self)
        payload.pop("failure_id")
        expected_failure_id = f"val_{canonical_sha256(payload)[:24]}"
        if self.failure_id != expected_failure_id:
            raise ValueError("failure_id does not match ValidationFailure Canonical content")

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def failure_id_for(failure: ValidationFailure) -> str:
    payload = asdict(failure)
    payload.pop("failure_id")
    return f"val_{canonical_sha256(payload)[:24]}"


def validation_failure(
    *,
    reason: str | ValidationReason,
    symbol: str,
    decision_time_utc_ms: int,
    affected_interval: str,
    decision_visible_input_hash: str | None,
    expected_values: tuple[tuple[str, str], ...],
    observed_values: tuple[tuple[str, str], ...],
    gap_intervals: tuple[tuple[int, int], ...],
    indicator_config_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> ValidationFailure:
    payload = {
        "schema_version": VALIDATION_FAILURE_SCHEMA_VERSION,
        "reason": ValidationReason(reason),
        "symbol": symbol,
        "decision_time_utc_ms": decision_time_utc_ms,
        "affected_interval": affected_interval,
        "decision_visible_input_hash": decision_visible_input_hash,
        "expected_values": tuple(sorted(expected_values)),
        "observed_values": tuple(sorted(observed_values)),
        "gap_intervals": tuple(sorted(gap_intervals)),
        "indicator_config_hash": indicator_config_hash,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
        "created_by": "PYTHON_DETERMINISTIC",
    }
    failure_id = f"val_{canonical_sha256(payload)[:24]}"
    return ValidationFailure(failure_id=failure_id, **payload)
