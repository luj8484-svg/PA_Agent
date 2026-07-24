from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from pa_agent.research_2d.parallel import TaskExecutionBatch, WatchdogConfig
from pa_agent.research_2d.runner import Scenario
from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS, StrategyIdentity
from pa_agent.research_v2a.identity import ExperimentIdentity
from pa_agent.research_v2a.walk_forward import (
    WalkForwardTask,
    WalkForwardTaskResult,
    WalkForwardWorkerPayload,
    execute_walk_forward_task,
    run_capacity_probe,
)


def _identity() -> ExperimentIdentity:
    return ExperimentIdentity(
        schema_version="V2A_EXPERIMENT_IDENTITY_V2",
        strategy_identities=(StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50),
        fold_manifest_hashes=("1" * 64,) * 4,
        threshold_manifest_hashes=("2" * 64,) * 4,
        threshold_calculation_hashes=("3" * 64,) * 4,
        dataset_content_hash="4" * 64,
        code_commit="5" * 40,
        dependency_lock_hash="6" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        execution_horizon_gate_version="V2A_EXECUTION_HORIZON_GATE_V1",
        execution_time_config_content_hash="8" * 64,
        maximum_holding_minutes=2880,
        max_hold_version="MAX_HOLD_V1_EXACT_48H",
        execution_horizon_decision_hashes=("9" * 64,) * 4,
        computational_experiment_id="7" * 64,
    )


def _task() -> WalkForwardTask:
    return WalkForwardTask(
        key="F4:V1_BASELINE:NATIVE_PRIMARY:BASE_1X",
        fold=WALK_FORWARD_FOLDS[3],
        strategy_identity=StrategyIdentity.V1_BASELINE,
        authority="NATIVE_PRIMARY",
        scenario=Scenario("BASE_1X", Decimal("1"), Decimal("1")),
        initial_capital=Decimal("10000"),
        accepted_candidate_ids=("cand_1",),
        accepted_candidate_content_hash="8" * 64,
        experiment_identity=_identity(),
    )


def test_capacity_probe_runs_only_f4_v1_and_disables_no_progress(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}

    def fake_run_tasks(tasks, **kwargs):
        captured["tasks"] = tasks
        captured.update(kwargs)
        result = SimpleNamespace(
            key=tasks[0].key,
            result_pickle_bytes=321,
            worker_peak_rss_bytes=456,
        )
        return TaskExecutionBatch((result,), "spawn", 123, 456, ())

    monkeypatch.setattr("pa_agent.research_v2a.walk_forward.run_tasks", fake_run_tasks)
    report = run_capacity_probe(
        task=_task(),
        root=tmp_path,
        diagnostics_output=tmp_path / "probe.json",
    )

    assert tuple(item.task.key for item in captured["tasks"]) == (
        "F4:V1_BASELINE:NATIVE_PRIMARY:BASE_1X",
    )
    assert captured["max_workers"] == 1
    assert captured["hard_timeout_seconds"] == 21_600
    assert captured["no_progress_timeout_seconds"] is None
    assert report.task_key == "F4:V1_BASELINE:NATIVE_PRIMARY:BASE_1X"
    assert report.worker_peak_rss_bytes == 456
    assert (tmp_path / "probe.json").is_file()


def test_capacity_probe_rejects_any_non_f4_v1_task(tmp_path: Path) -> None:
    wrong = _task()
    wrong = WalkForwardTask(
        **{name: getattr(wrong, name) for name in wrong.__dataclass_fields__ if name != "key"},
        key="F3:V1_BASELINE:NATIVE_PRIMARY:BASE_1X",
    )
    with pytest.raises(ValueError, match="F4"):
        run_capacity_probe(
            task=wrong,
            root=tmp_path,
            diagnostics_output=tmp_path / "probe.json",
        )


def test_capacity_probe_refuses_enabled_no_progress_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="disabled"):
        run_capacity_probe(
            task=_task(),
            root=tmp_path,
            diagnostics_output=tmp_path / "probe.json",
            no_progress_timeout_seconds=1200,  # type: ignore[arg-type]
        )


def test_worker_receives_disabled_no_progress_watchdog(monkeypatch, tmp_path: Path) -> None:
    observed = {}

    def fake_run(task, *, root, experiment_identity):
        observed["task"] = task
        observed["root"] = root
        observed["identity"] = experiment_identity
        return WalkForwardTaskResult(task.key, "F4", task.strategy_identity, (), ())

    monkeypatch.setattr("pa_agent.research_v2a.walk_forward.run_walk_forward_task", fake_run)
    task = _task()
    result = execute_walk_forward_task(
        WalkForwardWorkerPayload(task.key, task, tmp_path),
        watchdog_config=WatchdogConfig(21_600, None),
    )
    assert result.key == task.key
    assert observed["identity"] == task.experiment_identity

    with pytest.raises(ValueError, match="disabled"):
        execute_walk_forward_task(
            WalkForwardWorkerPayload(task.key, task, tmp_path),
            watchdog_config=WatchdogConfig(21_600, 1200),
        )
