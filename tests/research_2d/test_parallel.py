from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from pa_agent.research_2d.parallel import (
    EvaluationTask,
    EvaluationTaskResult,
    OutputRootLockedError,
    ParallelEvaluationError,
    current_rss_bytes,
    exclusive_output_lock,
    formal_task_keys,
    limit_numerical_threads,
    peak_rss_bytes,
    pickle_size,
    run_tasks,
)


@dataclass(frozen=True)
class _ProbeTask:
    key: str
    delay_seconds: float = 0
    mode: str = "success"


@dataclass(frozen=True)
class _ProbeResult:
    key: str


def _probe_worker(task: _ProbeTask, progress_queue) -> _ProbeResult:
    progress_queue.put((task.key, "STARTED", 0, None, 1, 1))
    if task.mode == "exception":
        raise RuntimeError(f"probe failure {task.key}")
    time.sleep(task.delay_seconds)
    progress_queue.put((task.key, "COMPLETED", 1, 60_000, 1, 1))
    return _ProbeResult(task.key)


def _task() -> EvaluationTask:
    return EvaluationTask(
        key="OOS:NATIVE_PRIMARY:BASE_1X",
        root=Path("approved-data"),
        split=SimpleNamespace(name="OOS"),
        authority="NATIVE_PRIMARY",
        scenario=SimpleNamespace(name="BASE_1X"),
        candidates=(),
        trends=(),
        evidence_data=(),
        experiment_id="a" * 64,
        approval_hash="b" * 64,
        code_commit="c" * 40,
        dependency_lock_hash="d" * 64,
    )


def test_formal_task_keys_are_unique_and_stable() -> None:
    keys = formal_task_keys()
    assert keys == (
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "TRAINING:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "VALIDATION:NATIVE_PRIMARY:BASE_1X",
        "VALIDATION:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "OOS:NATIVE_PRIMARY:BASE_1X",
        "OOS:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "OOS:NATIVE_PRIMARY:COMBINED_2X",
        "OOS:NATIVE_PRIMARY:FEE_SLIPPAGE_3X",
        "OOS:NATIVE_PRIMARY:FUNDING_2X",
    )
    assert len(keys) == len(set(keys))


def test_task_and_result_are_pickleable() -> None:
    task = _task()
    result = EvaluationTaskResult(
        key=task.key,
        runs=(),
        metrics=(),
        payload_pickle_bytes=pickle_size(task),
        result_pickle_bytes=0,
        worker_pid=123,
        worker_peak_rss_bytes=456,
    )
    result = replace(result, result_pickle_bytes=pickle_size(result))
    assert pickle.loads(pickle.dumps(task)) == task
    assert pickle.loads(pickle.dumps(result)) == result
    assert pickle_size(task) == len(pickle.dumps(task, protocol=pickle.HIGHEST_PROTOCOL))


def test_rss_measurements_are_positive_and_ordered() -> None:
    current = current_rss_bytes()
    peak = peak_rss_bytes()
    assert current > 0
    assert peak >= current


def test_worker_numerical_threads_are_limited(monkeypatch) -> None:
    names = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    for name in names:
        monkeypatch.setenv(name, "16")
    limit_numerical_threads()
    assert {name: __import__("os").environ[name] for name in names} == {name: "1" for name in names}


def test_completion_order_does_not_change_registry_order() -> None:
    tasks = (_ProbeTask("slow", 0.2), _ProbeTask("fast", 0.01))
    batch = run_tasks(
        tasks,
        max_workers=2,
        task_timeout_seconds=10,
        no_progress_timeout_seconds=5,
        worker=_probe_worker,
    )
    assert tuple(item.key for item in batch.results) == ("slow", "fast")
    assert batch.multiprocessing_start_method == "spawn"


def test_worker_exception_reports_key_and_traceback() -> None:
    with __import__("pytest").raises(ParallelEvaluationError) as caught:
        run_tasks(
            (_ProbeTask("broken", mode="exception"),),
            max_workers=1,
            task_timeout_seconds=10,
            no_progress_timeout_seconds=5,
            worker=_probe_worker,
        )
    assert caught.value.task_key == "broken"
    assert "probe failure broken" in caught.value.traceback_text


def test_task_runtime_timeout_reports_key() -> None:
    with __import__("pytest").raises(ParallelEvaluationError) as caught:
        run_tasks(
            (_ProbeTask("slow", 1),),
            max_workers=1,
            task_timeout_seconds=0.1,
            no_progress_timeout_seconds=5,
            worker=_probe_worker,
        )
    assert caught.value.task_key == "slow"
    assert "task runtime timeout" in caught.value.traceback_text


def test_no_progress_timeout_reports_key() -> None:
    with __import__("pytest").raises(ParallelEvaluationError) as caught:
        run_tasks(
            (_ProbeTask("stalled", 1),),
            max_workers=1,
            task_timeout_seconds=5,
            no_progress_timeout_seconds=0.1,
            worker=_probe_worker,
        )
    assert caught.value.task_key == "stalled"
    assert "no progress timeout" in caught.value.traceback_text


def test_keyboard_interrupt_is_fail_closed(monkeypatch) -> None:
    import pa_agent.research_2d.parallel as parallel

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(parallel, "as_completed", interrupted)
    with __import__("pytest").raises(ParallelEvaluationError) as caught:
        run_tasks(
            (_ProbeTask("interrupted", 1),),
            max_workers=1,
            task_timeout_seconds=5,
            no_progress_timeout_seconds=1,
            worker=_probe_worker,
        )
    assert caught.value.task_key == "PARENT"
    assert "KeyboardInterrupt" in caught.value.traceback_text


def test_output_lock_is_exclusive(tmp_path) -> None:
    with (
        exclusive_output_lock(tmp_path),
        __import__("pytest").raises(OutputRootLockedError),
        exclusive_output_lock(tmp_path),
    ):
        pass
