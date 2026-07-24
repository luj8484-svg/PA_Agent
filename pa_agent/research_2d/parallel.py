from __future__ import annotations

import ctypes
import multiprocessing
import os
import pickle
import sys
import time
import traceback
from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed,
)
from concurrent.futures import (
    TimeoutError as FuturesTimeoutError,
)
from contextlib import contextmanager
from ctypes import POINTER, Structure, byref, c_size_t, sizeof
from ctypes.wintypes import BOOL, DWORD, HANDLE
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty
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


@dataclass(frozen=True, slots=True)
class TaskExecutionBatch:
    results: tuple[object, ...]
    multiprocessing_start_method: str
    parent_peak_rss_bytes: int
    aggregate_worker_peak_rss_bytes: int
    heartbeats: tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True)
class WatchdogConfig:
    hard_timeout_seconds: float
    no_progress_timeout_seconds: float | None


class ParallelEvaluationError(RuntimeError):
    def __init__(self, task_key: str, traceback_text: str) -> None:
        super().__init__(f"parallel evaluation failed for {task_key}")
        self.task_key = task_key
        self.traceback_text = traceback_text


class OutputRootLockedError(RuntimeError):
    pass


def formal_task_keys() -> tuple[str, ...]:
    return (
        "OOS:NATIVE_PRIMARY:BASE_1X",
        "OOS:NATIVE_PRIMARY:COMBINED_2X",
        "OOS:NATIVE_PRIMARY:FEE_SLIPPAGE_3X",
        "OOS:NATIVE_PRIMARY:FUNDING_2X",
        "OOS:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "VALIDATION:NATIVE_PRIMARY:BASE_1X",
        "VALIDATION:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "TRAINING:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
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

    class _MemoryStatusEx(Structure):
        _fields_ = (
            ("dwLength", DWORD),
            ("dwMemoryLoad", DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
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


def physical_memory_status() -> tuple[int, int]:
    if sys.platform == "win32":
        status = _MemoryStatusEx()
        status.dwLength = sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return int(status.ullTotalPhys), int(status.ullAvailPhys)
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="ascii").splitlines():
            name, value = line.split(":", 1)
            values[name] = int(value.strip().split()[0]) * 1024
        return values["MemTotal"], values["MemAvailable"]
    page_size = os.sysconf("SC_PAGE_SIZE")
    total = os.sysconf("SC_PHYS_PAGES") * page_size
    available = os.sysconf("SC_AVPHYS_PAGES") * page_size
    return int(total), int(available)


@contextmanager
def exclusive_output_lock(output_root: Path):
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".research_2d.lock"
    handle = lock_path.open("a+b")
    acquired = False
    try:
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise OutputRootLockedError(f"output root is locked: {output_root}") from exc
        yield lock_path
    finally:
        if acquired:
            try:
                handle.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _terminate_executor(executor: ProcessPoolExecutor, futures: tuple[object, ...]) -> None:
    for future in futures:
        future.cancel()
    processes = tuple(getattr(executor, "_processes", {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=5)
    executor.shutdown(wait=False, cancel_futures=True)


def _drain_heartbeats(
    progress_queue: Any,
    heartbeats: list[tuple[object, ...]],
    started_at: dict[str, float],
    last_progress: dict[str, float],
    worker_rss: dict[int, int],
) -> int:
    aggregate_peak = sum(worker_rss.values())
    while True:
        try:
            message = tuple(progress_queue.get_nowait())
        except Empty:
            break
        heartbeats.append(message)
        key, kind, _processed, _minute, pid, rss = message
        now = time.monotonic()
        if kind == "STARTED":
            started_at[str(key)] = now
        last_progress[str(key)] = now
        worker_rss[int(pid)] = int(rss)
        aggregate_peak = max(aggregate_peak, sum(worker_rss.values()))
    return aggregate_peak


def run_tasks(
    tasks: tuple[object, ...],
    *,
    max_workers: int,
    hard_timeout_seconds: float | None = None,
    no_progress_timeout_seconds: float | None = None,
    worker=None,
    result_validator=None,
    task_timeout_seconds: float | None = None,
) -> TaskExecutionBatch:
    if max_workers not in {1, 2, 6}:
        raise ValueError("max_workers must be one of 1, 2, or 6")
    if hard_timeout_seconds is not None and task_timeout_seconds is not None:
        raise ValueError("hard timeout must not use both canonical and legacy names")
    effective_hard_timeout = (
        hard_timeout_seconds if hard_timeout_seconds is not None else task_timeout_seconds
    )
    if effective_hard_timeout is None or effective_hard_timeout <= 0:
        raise ValueError("hard timeout must be positive")
    if no_progress_timeout_seconds is not None and no_progress_timeout_seconds <= 0:
        raise ValueError("enabled no-progress timeout must be positive")
    if worker is None:
        worker = execute_evaluation_task
    keys = tuple(str(task.key) for task in tasks)
    if len(keys) != len(set(keys)):
        raise ValueError("task keys must be unique")
    for task in tasks:
        pickle.loads(pickle.dumps(task, protocol=pickle.HIGHEST_PROTOCOL))
    pickle.dumps(worker, protocol=pickle.HIGHEST_PROTOCOL)
    watchdog_config = WatchdogConfig(
        hard_timeout_seconds=effective_hard_timeout,
        no_progress_timeout_seconds=no_progress_timeout_seconds,
    )
    watchdog_config = pickle.loads(pickle.dumps(watchdog_config, protocol=pickle.HIGHEST_PROTOCOL))
    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    progress_queue = manager.Queue()
    executor = ProcessPoolExecutor(max_workers=max_workers, mp_context=context)
    futures: dict[object, str] = {}
    results: dict[str, object] = {}
    heartbeats: list[tuple[object, ...]] = []
    started_at: dict[str, float] = {}
    last_progress: dict[str, float] = {}
    worker_rss: dict[int, int] = {}
    aggregate_peak = 0
    try:
        futures = {
            executor.submit(worker, task, progress_queue, watchdog_config): str(task.key)
            for task in tasks
        }
        pending = set(futures)
        while pending:
            aggregate_peak = max(
                aggregate_peak,
                _drain_heartbeats(
                    progress_queue,
                    heartbeats,
                    started_at,
                    last_progress,
                    worker_rss,
                ),
            )
            completed = []
            try:
                for future in as_completed(tuple(pending), timeout=0.05):
                    completed.append(future)
            except FuturesTimeoutError:
                pass
            for future in completed:
                pending.remove(future)
                key = futures[future]
                try:
                    result = future.result()
                except BaseException as exc:
                    raise ParallelEvaluationError(key, traceback.format_exc()) from exc
                if str(result.key) != key:
                    raise ParallelEvaluationError(
                        key, f"worker returned mismatched task key {result.key!r}"
                    )
                if result_validator is not None:
                    try:
                        result_validator(result)
                    except BaseException as exc:
                        raise ParallelEvaluationError(key, traceback.format_exc()) from exc
                results[key] = result
            now = time.monotonic()
            for future in pending:
                key = futures[future]
                started = started_at.get(key)
                if started is None:
                    continue
                if now - started > effective_hard_timeout:
                    raise ParallelEvaluationError(
                        key,
                        f"HARD_TIMEOUT after {effective_hard_timeout} seconds\n"
                        + "".join(traceback.format_stack()),
                    )
                if (
                    no_progress_timeout_seconds is not None
                    and now - last_progress.get(key, started) > no_progress_timeout_seconds
                ):
                    raise ParallelEvaluationError(
                        key,
                        f"NO_PROGRESS_TIMEOUT after {no_progress_timeout_seconds} seconds\n"
                        + "".join(traceback.format_stack()),
                    )
        aggregate_peak = max(
            aggregate_peak,
            _drain_heartbeats(
                progress_queue,
                heartbeats,
                started_at,
                last_progress,
                worker_rss,
            ),
        )
        executor.shutdown(wait=True, cancel_futures=False)
    except BaseException as exc:
        _terminate_executor(executor, tuple(futures))
        if isinstance(exc, ParallelEvaluationError):
            raise
        raise ParallelEvaluationError("PARENT", traceback.format_exc()) from exc
    finally:
        manager.shutdown()
    return TaskExecutionBatch(
        results=tuple(results[key] for key in keys),
        multiprocessing_start_method=context.get_start_method(),
        parent_peak_rss_bytes=peak_rss_bytes(),
        aggregate_worker_peak_rss_bytes=aggregate_peak,
        heartbeats=tuple(heartbeats),
    )


def _put_progress(progress_queue: Any, message: tuple[object, ...]) -> None:
    if progress_queue is not None:
        progress_queue.put(message)


def execute_evaluation_task(
    task: EvaluationTask,
    progress_queue: Any = None,
    watchdog_config: WatchdogConfig | None = None,
) -> EvaluationTaskResult:
    limit_numerical_threads()
    if watchdog_config is None:
        raise ValueError("worker watchdog config is required")
    print(
        f"worker_start task_key={task.key} "
        f"hard_timeout_seconds={watchdog_config.hard_timeout_seconds} "
        f"no_progress_timeout_seconds={watchdog_config.no_progress_timeout_seconds}",
        flush=True,
    )
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
