from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from pa_agent.research_2d.parallel import (
    EvaluationTask,
    EvaluationTaskResult,
    formal_task_keys,
    pickle_size,
)


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
