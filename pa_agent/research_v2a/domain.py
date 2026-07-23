from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("time must be UTC")
    return int(parsed.timestamp() * 1000)


class StrategyIdentity(StrEnum):
    V1_BASELINE = "V1_BASELINE"
    V2A_Q50 = "V2A_Q50"
    V2A_Q67 = "V2A_Q67"


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    training_start_utc_ms: int
    training_end_utc_ms: int
    validation_start_utc_ms: int
    validation_end_utc_ms: int

    def __post_init__(self) -> None:
        if self.fold_id not in {"F1", "F2", "F3", "F4"}:
            raise ValueError("unsupported Fold identity")
        if not (
            self.training_start_utc_ms
            <= self.training_end_utc_ms
            < self.validation_start_utc_ms
            <= self.validation_end_utc_ms
        ):
            raise ValueError("Fold boundaries must be ordered and non-overlapping")


@dataclass(frozen=True, slots=True)
class DeploymentThresholdWindow:
    application_start_utc_ms: int
    application_end_utc_ms: int | None
    training_start_utc_ms: int
    training_end_utc_ms: int

    def __post_init__(self) -> None:
        if self.training_start_utc_ms > self.training_end_utc_ms:
            raise ValueError("threshold Training boundaries are reversed")
        if self.training_end_utc_ms + 1 != self.application_start_utc_ms:
            raise ValueError("threshold Training must end immediately before application")
        if (
            self.application_end_utc_ms is not None
            and self.application_end_utc_ms < self.application_start_utc_ms
        ):
            raise ValueError("application boundaries are reversed")


def _end_before(value: str) -> int:
    return _utc_ms(value) - 1


WALK_FORWARD_FOLDS = (
    WalkForwardFold(
        "F1",
        _utc_ms("2020-10-01T00:00:00Z"),
        _end_before("2022-10-01T00:00:00Z"),
        _utc_ms("2022-10-01T00:00:00Z"),
        _end_before("2023-04-01T00:00:00Z"),
    ),
    WalkForwardFold(
        "F2",
        _utc_ms("2021-04-01T00:00:00Z"),
        _end_before("2023-04-01T00:00:00Z"),
        _utc_ms("2023-04-01T00:00:00Z"),
        _end_before("2023-10-01T00:00:00Z"),
    ),
    WalkForwardFold(
        "F3",
        _utc_ms("2021-10-01T00:00:00Z"),
        _end_before("2023-10-01T00:00:00Z"),
        _utc_ms("2023-10-01T00:00:00Z"),
        _end_before("2024-04-01T00:00:00Z"),
    ),
    WalkForwardFold(
        "F4",
        _utc_ms("2022-04-01T00:00:00Z"),
        _end_before("2024-04-01T00:00:00Z"),
        _utc_ms("2024-04-01T00:00:00Z"),
        _end_before("2024-10-01T00:00:00Z"),
    ),
)


DEPLOYMENT_THRESHOLD_WINDOWS = (
    DeploymentThresholdWindow(
        _utc_ms("2024-10-01T00:00:00Z"),
        _end_before("2025-04-01T00:00:00Z"),
        _utc_ms("2022-10-01T00:00:00Z"),
        _end_before("2024-10-01T00:00:00Z"),
    ),
    DeploymentThresholdWindow(
        _utc_ms("2025-04-01T00:00:00Z"),
        _end_before("2025-10-01T00:00:00Z"),
        _utc_ms("2023-04-01T00:00:00Z"),
        _end_before("2025-04-01T00:00:00Z"),
    ),
    DeploymentThresholdWindow(
        _utc_ms("2025-10-01T00:00:00Z"),
        _end_before("2026-04-01T00:00:00Z"),
        _utc_ms("2023-10-01T00:00:00Z"),
        _end_before("2025-10-01T00:00:00Z"),
    ),
    DeploymentThresholdWindow(
        _utc_ms("2026-04-01T00:00:00Z"),
        None,
        _utc_ms("2024-04-01T00:00:00Z"),
        _end_before("2026-04-01T00:00:00Z"),
    ),
)
