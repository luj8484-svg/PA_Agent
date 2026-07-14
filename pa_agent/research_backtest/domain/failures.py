from __future__ import annotations

from dataclasses import asdict, dataclass, replace

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
    failure = ValidationFailure(
        schema_version=VALIDATION_FAILURE_SCHEMA_VERSION,
        failure_id="",
        reason=ValidationReason(reason),
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        affected_interval=affected_interval,
        decision_visible_input_hash=decision_visible_input_hash,
        expected_values=tuple(sorted(expected_values)),
        observed_values=tuple(sorted(observed_values)),
        gap_intervals=tuple(sorted(gap_intervals)),
        indicator_config_hash=indicator_config_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
        created_by="PYTHON_DETERMINISTIC",
    )
    return replace(failure, failure_id=failure_id_for(failure))
