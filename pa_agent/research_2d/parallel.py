from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

NUMERICAL_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    key: str
    root: Path
    split: object
    authority: str
    scenario: object
    candidates: tuple[object, ...]
    trends: tuple[object, ...]
    evidence_data: tuple[object, ...]
    experiment_id: str
    approval_hash: str
    code_commit: str
    dependency_lock_hash: str


@dataclass(frozen=True, slots=True)
class EvaluationTaskResult:
    key: str
    runs: tuple[object, ...]
    metrics: tuple[dict[str, object], ...]
    payload_pickle_bytes: int
    result_pickle_bytes: int
    worker_pid: int
    worker_peak_rss_bytes: int


def formal_task_keys() -> tuple[str, ...]:
    return (
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


def pickle_size(value: object) -> int:
    return len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def _put_progress(progress_queue: Any, message: tuple[object, ...]) -> None:
    if progress_queue is not None:
        progress_queue.put(message)


def execute_evaluation_task(
    task: EvaluationTask, progress_queue: Any = None
) -> EvaluationTaskResult:
    for name in NUMERICAL_THREAD_ENV:
        os.environ[name] = "1"
    _put_progress(progress_queue, (task.key, "STARTED", 0, None, os.getpid(), 0))
    from pa_agent.research_2d.runner import _run_scenario

    runs, metrics = _run_scenario(
        root=task.root,
        split=task.split,
        authority=task.authority,
        scenario=task.scenario,
        candidates=task.candidates,
        trends=task.trends,
        evidence_data=task.evidence_data,
        experiment_id=task.experiment_id,
        approval_hash=task.approval_hash,
        code_commit=task.code_commit,
        dependency_lock_hash=task.dependency_lock_hash,
    )
    result = EvaluationTaskResult(
        key=task.key,
        runs=tuple(runs),
        metrics=tuple(metrics),
        payload_pickle_bytes=pickle_size(task),
        result_pickle_bytes=0,
        worker_pid=os.getpid(),
        worker_peak_rss_bytes=0,
    )
    result = replace(result, result_pickle_bytes=pickle_size(result))
    _put_progress(progress_queue, (task.key, "COMPLETED", 0, None, os.getpid(), 0))
    return result
