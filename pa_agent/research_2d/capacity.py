from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.approval import verify_data_approval_manifest
from pa_agent.research_2d.parallel import (
    EvaluationTask,
    current_rss_bytes,
    physical_memory_status,
    pickle_size,
    run_tasks,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256


def capacity_projection(candidates: tuple[object, ...], result: object) -> dict[str, object]:
    runs = tuple(
        {
            "path_kind": run.path_kind,
            "state": run.state,
            "path_result": run.path_result,
            "fills": run.fills,
            "trades": run.trades,
            "ledger_entries": run.ledger_entries,
            "planning_outputs": run.planning_outputs,
            "daily_equity_points": run.daily_equity_points,
            "event_counts": run.event_counts,
            "processed_minute_count": run.processed_minute_count,
            "gap_context": run.gap_context,
        }
        for run in result.runs
    )
    return {
        "candidates": candidates,
        "runs": runs,
        "metrics": result.metrics,
    }


def capacity_projection_hash(candidates: tuple[object, ...], result: object) -> str:
    from pa_agent.research_2d.runner import canonical_report_value

    return canonical_sha256(canonical_report_value(capacity_projection(candidates, result)))


def select_safe_worker_count(
    measurements: dict[str, dict[str, object]], *, available_memory_bytes: int
) -> int:
    safe = [
        int(workers)
        for workers, value in measurements.items()
        if value["passed"] and int(value["memory_with_margin_bytes"]) < available_memory_bytes
    ]
    if not safe:
        raise RuntimeError("no measured worker count satisfies the memory safety gate")
    return max(safe)


def build_real_capacity_tasks(
    *,
    root: Path,
    code_commit: str,
    duration_days: int = 5,
    task_count: int = 6,
) -> tuple[EvaluationTask, ...]:
    from pa_agent.research_2d.runner import (
        Scenario,
        Split,
        _load_candidates,
        _market_evidence,
        _splits,
    )

    if duration_days <= 0 or task_count <= 0:
        raise ValueError("capacity duration and task count must be positive")
    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    import json

    split_manifest = json.loads(
        (root / "experiment_split_candidate_v3.json").read_text(encoding="utf-8")
    )
    splits = _splits(split_manifest)
    oos = splits[-1]
    fixture = Split(
        "OOS",
        oos.start_utc_ms,
        min(oos.end_utc_ms, oos.start_utc_ms + duration_days * 86_400_000 - 1),
    )
    candidates, trends, _, _ = _load_candidates(
        root,
        fixture,
        "NATIVE_PRIMARY",
        splits[0].start_utc_ms,
        code_commit,
        approval.manifest["dependency_lock_hash"],
    )
    evidence = _market_evidence(root, fixture, candidates, trends)
    experiment_id = canonical_sha256(
        {
            "kind": "RESEARCH_2D_REAL_CAPACITY_FIXTURE_V1",
            "approval_hash": approval.manifest_hash,
            "code_commit": code_commit,
            "start_utc_ms": fixture.start_utc_ms,
            "end_utc_ms": fixture.end_utc_ms,
        }
    )
    scenario = Scenario("BASE_1X", Decimal("1"), Decimal("1"))
    return tuple(
        EvaluationTask(
            key=f"CAPACITY:{index:02d}",
            root=root,
            split=fixture,
            authority="NATIVE_PRIMARY",
            scenario=scenario,
            candidates=candidates,
            trends=trends,
            evidence_data=evidence,
            experiment_id=experiment_id,
            approval_hash=approval.manifest_hash,
            code_commit=code_commit,
            dependency_lock_hash=approval.manifest["dependency_lock_hash"],
        )
        for index in range(task_count)
    )


def run_capacity_matrix(
    tasks: tuple[EvaluationTask, ...],
    *,
    worker_counts: tuple[int, ...] = (1, 2, 6),
    task_timeout_seconds: float = 3_600,
    no_progress_timeout_seconds: float = 600,
) -> dict[str, object]:
    total_memory, available_at_start = physical_memory_status()
    measurements: dict[str, dict[str, object]] = {}
    reference_hashes: dict[str, str] | None = None
    for workers in worker_counts:
        current_before = current_rss_bytes()
        started = time.perf_counter()
        batch = run_tasks(
            tasks,
            max_workers=workers,
            task_timeout_seconds=task_timeout_seconds,
            no_progress_timeout_seconds=no_progress_timeout_seconds,
        )
        elapsed = time.perf_counter() - started
        hashes = {
            task.key: capacity_projection_hash(task.candidates, result)
            for task, result in zip(tasks, batch.results, strict=True)
        }
        if reference_hashes is None:
            reference_hashes = hashes
        equivalent = hashes == reference_hashes
        measured_peak = batch.parent_peak_rss_bytes + batch.aggregate_worker_peak_rss_bytes
        measurements[str(workers)] = {
            "passed": equivalent,
            "economic_projection_hashes": hashes,
            "elapsed_seconds": elapsed,
            "parent_current_rss_before_bytes": current_before,
            "parent_current_rss_after_bytes": current_rss_bytes(),
            "parent_peak_rss_bytes": batch.parent_peak_rss_bytes,
            "aggregate_worker_peak_rss_bytes": batch.aggregate_worker_peak_rss_bytes,
            "memory_with_margin_bytes": measured_peak * 5 // 4,
            "payload_pickle_bytes": {task.key: pickle_size(task) for task in tasks},
            "result_pickle_bytes": {
                result.key: result.result_pickle_bytes for result in batch.results
            },
            "worker_peak_rss_bytes": {
                result.key: result.worker_peak_rss_bytes for result in batch.results
            },
            "heartbeat_count": len(batch.heartbeats),
            "multiprocessing_start_method": batch.multiprocessing_start_method,
        }
    selected = select_safe_worker_count(measurements, available_memory_bytes=available_at_start)
    return {
        "schema_version": "RESEARCH_2D_CAPACITY_REPORT_V1",
        "total_physical_memory_bytes": total_memory,
        "available_memory_at_start_bytes": available_at_start,
        "task_count": len(tasks),
        "task_keys": tuple(task.key for task in tasks),
        "measurements": measurements,
        "selected_workers": selected,
    }
