from __future__ import annotations

import ctypes
import os
import pickle
import sys
from ctypes import POINTER, Structure, byref, c_size_t, sizeof
from ctypes.wintypes import BOOL, DWORD, HANDLE
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


def limit_numerical_threads() -> None:
    for name in NUMERICAL_THREAD_ENV:
        os.environ[name] = "1"


if sys.platform == "win32":

    class _ProcessMemoryCounters(Structure):
        _fields_ = (
            ("cb", DWORD),
            ("PageFaultCount", DWORD),
            ("PeakWorkingSetSize", c_size_t),
            ("WorkingSetSize", c_size_t),
            ("QuotaPeakPagedPoolUsage", c_size_t),
            ("QuotaPagedPoolUsage", c_size_t),
            ("QuotaPeakNonPagedPoolUsage", c_size_t),
            ("QuotaNonPagedPoolUsage", c_size_t),
            ("PagefileUsage", c_size_t),
            ("PeakPagefileUsage", c_size_t),
        )

    _get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    _get_process_memory_info.argtypes = (
        HANDLE,
        POINTER(_ProcessMemoryCounters),
        DWORD,
    )
    _get_process_memory_info.restype = BOOL


def _windows_memory_counters() -> tuple[int, int]:
    counters = _ProcessMemoryCounters()
    counters.cb = sizeof(counters)
    if not _get_process_memory_info(
        ctypes.windll.kernel32.GetCurrentProcess(), byref(counters), counters.cb
    ):
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def current_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_memory_counters()[0]
    statm = Path("/proc/self/statm")
    if statm.exists():
        resident_pages = int(statm.read_text(encoding="ascii").split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    import resource

    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def peak_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_memory_counters()[1]
    import resource

    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _put_progress(progress_queue: Any, message: tuple[object, ...]) -> None:
    if progress_queue is not None:
        progress_queue.put(message)


def execute_evaluation_task(
    task: EvaluationTask, progress_queue: Any = None
) -> EvaluationTaskResult:
    limit_numerical_threads()
    _put_progress(progress_queue, (task.key, "STARTED", 0, None, os.getpid(), 0))
    from pa_agent.research_2d.runner import _run_scenario

    def progress(processed: int, minute_utc_ms: int) -> None:
        _put_progress(
            progress_queue,
            (
                task.key,
                "PROGRESS",
                processed,
                minute_utc_ms,
                os.getpid(),
                current_rss_bytes(),
            ),
        )

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
        progress_callback=progress,
    )
    result = EvaluationTaskResult(
        key=task.key,
        runs=tuple(runs),
        metrics=tuple(metrics),
        payload_pickle_bytes=pickle_size(task),
        result_pickle_bytes=0,
        worker_pid=os.getpid(),
        worker_peak_rss_bytes=peak_rss_bytes(),
    )
    result = replace(result, result_pickle_bytes=pickle_size(result))
    _put_progress(
        progress_queue,
        (task.key, "COMPLETED", 0, None, os.getpid(), current_rss_bytes()),
    )
    return result
