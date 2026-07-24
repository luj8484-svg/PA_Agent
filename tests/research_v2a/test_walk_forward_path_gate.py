from __future__ import annotations

from types import SimpleNamespace

import pytest

from pa_agent.research_backtest.domain.rejections import ExecutionRejection
from pa_agent.research_v2a.domain import StrategyIdentity
from pa_agent.research_v2a.walk_forward import (
    WalkForwardTaskResult,
    WalkForwardWorkerResult,
    validate_walk_forward_worker_result,
)


def _data_invalid_rejection() -> ExecutionRejection:
    rejection = object.__new__(ExecutionRejection)
    object.__setattr__(rejection, "reason", SimpleNamespace(value="DATA_INVALID"))
    return rejection


def _run(
    path: str,
    *,
    state: str = "VALID",
    processed: int = 10,
    invalid_reason: str | None = None,
    planning_outputs: tuple[object, ...] = (),
):
    return SimpleNamespace(
        path_kind=SimpleNamespace(value=path),
        path_result=SimpleNamespace(
            path_state=SimpleNamespace(value=state),
            invalid_reason=invalid_reason,
            final_processed_time_utc_ms=processed,
        ),
        planning_outputs=planning_outputs,
        trades=(),
    )


def _worker(
    baseline,
    conservative,
) -> WalkForwardWorkerResult:
    task_result = WalkForwardTaskResult(
        key="F1:V2A_Q50:NATIVE_PRIMARY:BASE_1X",
        fold_id="F1",
        strategy_identity=StrategyIdentity.V2A_Q50,
        runs=(baseline, conservative),
        metrics=(
            {
                "path_kind": "BASELINE",
                "split_end_utc_ms": 9,
                "engine_peak_observed_drawdown": "0",
            },
            {
                "path_kind": "CONSERVATIVE",
                "split_end_utc_ms": 9,
                "engine_peak_observed_drawdown": "0",
            },
        ),
    )
    return WalkForwardWorkerResult(task_result.key, task_result, 0, 0, 1, 1)


def test_completed_path_with_planning_data_invalid_fails_gate() -> None:
    result = _worker(
        _run("BASELINE", planning_outputs=(_data_invalid_rejection(),)),
        _run("CONSERVATIVE"),
    )
    with pytest.raises(ValueError, match="DATA_INVALID"):
        validate_walk_forward_worker_result(result)


def test_invalid_path_fails_even_when_final_time_reaches_end() -> None:
    result = _worker(
        _run("BASELINE", state="INVALID", invalid_reason="MARK_GAP_AFFECTS_POSITION"),
        _run("CONSERVATIVE"),
    )
    with pytest.raises(ValueError, match="INVALID"):
        validate_walk_forward_worker_result(result)


def test_conservative_invalid_fails_even_when_baseline_is_valid() -> None:
    result = _worker(
        _run("BASELINE"),
        _run("CONSERVATIVE", state="INVALID", invalid_reason="ACCOUNT_CONSERVATION_FAILED"),
    )
    with pytest.raises(ValueError, match="CONSERVATIVE"):
        validate_walk_forward_worker_result(result)
