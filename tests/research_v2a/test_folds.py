from datetime import UTC, datetime

from pa_agent.research_v2a.domain import DEPLOYMENT_THRESHOLD_WINDOWS, WALK_FORWARD_FOLDS


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def test_four_walk_forward_folds_have_frozen_utc_boundaries() -> None:
    assert tuple(
        (
            fold.fold_id,
            fold.training_start_utc_ms,
            fold.training_end_utc_ms,
            fold.validation_start_utc_ms,
            fold.validation_end_utc_ms,
        )
        for fold in WALK_FORWARD_FOLDS
    ) == (
        (
            "F1",
            _ms("2020-10-01T00:00:00Z"),
            _ms("2022-10-01T00:00:00Z") - 1,
            _ms("2022-10-01T00:00:00Z"),
            _ms("2023-04-01T00:00:00Z") - 1,
        ),
        (
            "F2",
            _ms("2021-04-01T00:00:00Z"),
            _ms("2023-04-01T00:00:00Z") - 1,
            _ms("2023-04-01T00:00:00Z"),
            _ms("2023-10-01T00:00:00Z") - 1,
        ),
        (
            "F3",
            _ms("2021-10-01T00:00:00Z"),
            _ms("2023-10-01T00:00:00Z") - 1,
            _ms("2023-10-01T00:00:00Z"),
            _ms("2024-04-01T00:00:00Z") - 1,
        ),
        (
            "F4",
            _ms("2022-04-01T00:00:00Z"),
            _ms("2024-04-01T00:00:00Z") - 1,
            _ms("2024-04-01T00:00:00Z"),
            _ms("2024-10-01T00:00:00Z") - 1,
        ),
    )
    assert all(
        fold.validation_start_utc_ms > fold.training_end_utc_ms for fold in WALK_FORWARD_FOLDS
    )
    assert (
        datetime.fromtimestamp(
            WALK_FORWARD_FOLDS[0].training_start_utc_ms / 1000, tz=UTC
        ).isoformat()
        == "2020-10-01T00:00:00+00:00"
    )


def test_deployment_threshold_windows_use_previous_complete_24_months() -> None:
    assert tuple(
        (
            window.application_start_utc_ms,
            window.application_end_utc_ms,
            window.training_start_utc_ms,
            window.training_end_utc_ms,
        )
        for window in DEPLOYMENT_THRESHOLD_WINDOWS
    ) == (
        (
            _ms("2024-10-01T00:00:00Z"),
            _ms("2025-04-01T00:00:00Z") - 1,
            _ms("2022-10-01T00:00:00Z"),
            _ms("2024-10-01T00:00:00Z") - 1,
        ),
        (
            _ms("2025-04-01T00:00:00Z"),
            _ms("2025-10-01T00:00:00Z") - 1,
            _ms("2023-04-01T00:00:00Z"),
            _ms("2025-04-01T00:00:00Z") - 1,
        ),
        (
            _ms("2025-10-01T00:00:00Z"),
            _ms("2026-04-01T00:00:00Z") - 1,
            _ms("2023-10-01T00:00:00Z"),
            _ms("2025-10-01T00:00:00Z") - 1,
        ),
        (
            _ms("2026-04-01T00:00:00Z"),
            None,
            _ms("2024-04-01T00:00:00Z"),
            _ms("2026-04-01T00:00:00Z") - 1,
        ),
    )
