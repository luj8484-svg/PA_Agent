from types import SimpleNamespace

import pytest

from pa_agent.research_2d.runner import (
    FormalEvaluationGateError,
    TaskDisposition,
    assess_formal_task_result,
    performance_results,
    run_prioritized_task_phases,
)


def _run(path: str, state: str, reason: str | None = None, processed: int = 10):
    return SimpleNamespace(
        path_kind=SimpleNamespace(value=path),
        path_result=SimpleNamespace(
            path_state=SimpleNamespace(value=state),
            invalid_reason=reason,
            final_processed_time_utc_ms=processed,
        ),
        planning_outputs=(),
    )


def _result(key: str, state: str, reason: str | None = None):
    return SimpleNamespace(
        key=key,
        runs=(
            _run("BASELINE", state, reason),
            _run("CONSERVATIVE", state, reason),
        ),
        metrics=(
            {"split_end_utc_ms": 9, "net_return": "0.01"},
            {"split_end_utc_ms": 9, "net_return": "0.01"},
        ),
    )


def test_training_mark_gap_is_diagnostic_and_oos_phase_runs_first() -> None:
    calls = []
    tasks = (
        SimpleNamespace(key="OOS:NATIVE_PRIMARY:BASE_1X"),
        SimpleNamespace(key="TRAINING:NATIVE_PRIMARY:BASE_1X"),
    )
    results = {
        tasks[0].key: _result(tasks[0].key, "VALID"),
        tasks[1].key: _result(tasks[1].key, "INVALID", "MARK_GAP_AFFECTS_POSITION:BTCUSDT"),
    }

    def batch_runner(phase, **kwargs):
        calls.append(tuple(task.key for task in phase))
        phase_results = tuple(results[task.key] for task in phase)
        for result in phase_results:
            kwargs["result_validator"](result)
        return SimpleNamespace(
            results=phase_results,
            multiprocessing_start_method="spawn",
            parent_peak_rss_bytes=1,
            aggregate_worker_peak_rss_bytes=1,
            heartbeats=(),
        )

    batch = run_prioritized_task_phases(
        tasks,
        max_workers=2,
        hard_timeout_seconds=10,
        no_progress_timeout_seconds=5,
        batch_runner=batch_runner,
    )

    assert calls == [
        ("OOS:NATIVE_PRIMARY:BASE_1X",),
        ("TRAINING:NATIVE_PRIMARY:BASE_1X",),
    ]
    assert (
        assess_formal_task_result(results[tasks[1].key]).status
        is TaskDisposition.DIAGNOSTIC_DATA_GAP
    )
    assert tuple(result.key for result in batch.results) == tuple(task.key for task in tasks)


def test_training_other_invalid_stops_experiment() -> None:
    result = _result(
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "INVALID",
        "ACCOUNT_CONSERVATION_FAILED",
    )
    with pytest.raises(FormalEvaluationGateError, match="DATA_EXECUTION_INVALID"):
        assess_formal_task_result(result)


def test_oos_mark_gap_stops_experiment() -> None:
    result = _result(
        "OOS:NATIVE_PRIMARY:BASE_1X",
        "INVALID",
        "MARK_GAP_AFFECTS_POSITION:BTCUSDT",
    )
    with pytest.raises(FormalEvaluationGateError) as caught:
        assess_formal_task_result(result)
    assert caught.value.conclusion == "DATA_EXECUTION_INVALID"


def test_diagnostic_invalid_result_is_excluded_from_performance() -> None:
    training = _result(
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "INVALID",
        "MARK_GAP_AFFECTS_POSITION:BTCUSDT",
    )
    oos = _result("OOS:NATIVE_PRIMARY:BASE_1X", "VALID")

    included = performance_results((training, oos))

    assert tuple(result.key for result in included) == (oos.key,)


def test_valid_oos_with_training_diagnostic_can_produce_strategy_conclusion() -> None:
    training = _result(
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "INVALID",
        "MARK_GAP_AFFECTS_POSITION:BTCUSDT",
    )
    oos = _result("OOS:NATIVE_PRIMARY:BASE_1X", "VALID")

    assert assess_formal_task_result(training).status is TaskDisposition.DIAGNOSTIC_DATA_GAP
    assert assess_formal_task_result(oos).status is TaskDisposition.COMPLETED
    assert performance_results((training, oos)) == (oos,)
