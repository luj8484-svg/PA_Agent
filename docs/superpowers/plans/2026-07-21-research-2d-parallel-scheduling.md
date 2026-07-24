# Research 2D Parallel Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the frozen Research 2D scenario registry with bounded, spawn-safe process parallelism while preserving byte-identical canonical economics and failing closed before publication.

**Architecture:** A parent-only orchestrator prepares immutable pickleable tasks, holds the output-root lock, and executes module-level workers through an explicit `spawn` `ProcessPoolExecutor`. Workers read approved inputs and return in-memory results plus heartbeats/RSS diagnostics; the parent observes futures with `as_completed`, reconstructs results in registry order, creates canonical artifacts only after total success, and writes non-canonical runtime diagnostics separately.

**Tech Stack:** CPython 3.12.13 standard library (`concurrent.futures`, `multiprocessing`, `pickle`, `ctypes`, `msvcrt`/`fcntl`, `traceback`), pytest, Ruff.

## Global Constraints

- Supported worker counts are exactly `1`, `2`, and `6`; the formal count is chosen from measured RSS and serialization results.
- Windows uses explicit `multiprocessing.get_context("spawn")`; worker callables are module-level and all task/result values pass pickle round trips.
- Worker numerical thread variables `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` equal `1`.
- No file under `pa_agent/research_backtest` changes.
- Workers are read-only and never write artifacts; only the parent atomically publishes after every task succeeds.
- Failure, timeout, no-progress, or Ctrl+C cancels pending work, identifies the task key, records a full traceback, cleans temporary state, and publishes nothing.
- Runtime diagnostics never affect computational experiment identity or canonical artifact hashes.

---

### Task 1: Immutable task registry and spawn-safe worker contract

**Files:**
- Create: `pa_agent/research_2d/parallel.py`
- Modify: `pa_agent/research_2d/runner.py`
- Test: `tests/research_2d/test_parallel.py`

**Interfaces:**
- Produces: `EvaluationTask`, `EvaluationTaskResult`, `formal_task_keys()`, `pickle_size(value)`, and module-level `execute_evaluation_task(task, progress_queue)`.
- Consumes: existing `Split`, `Scenario`, `_run_scenario`, Candidate/trend/evidence tuples.

- [ ] **Step 1: Write failing registry and pickle tests**

```python
def test_formal_task_keys_are_unique_and_stable():
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

def test_task_and_result_are_pickleable(task_fixture, result_fixture):
    assert pickle.loads(pickle.dumps(task_fixture)) == task_fixture
    assert pickle.loads(pickle.dumps(result_fixture)) == result_fixture
```

- [ ] **Step 2: Run tests and verify imports fail**

Run: `python -m pytest tests/research_2d/test_parallel.py -q`

Expected: FAIL because `pa_agent.research_2d.parallel` does not exist.

- [ ] **Step 3: Implement frozen dataclasses, registry, serialization measurement, and top-level worker**

```python
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
```

The worker sets all four numerical thread environment variables to `1`, emits `STARTED` and `COMPLETED` heartbeats, calls `_run_scenario`, measures its own peak RSS with the cross-platform helper, and returns `EvaluationTaskResult`.

- [ ] **Step 4: Verify focused and Research 2D tests pass**

Run: `python -m pytest tests/research_2d/test_parallel.py tests/research_2d -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pa_agent/research_2d/parallel.py pa_agent/research_2d/runner.py tests/research_2d/test_parallel.py
git commit -m "feat(research-2d): define spawn-safe evaluation tasks"
```

### Task 2: Progress heartbeat and exact resource measurements

**Files:**
- Modify: `pa_agent/research_2d/streaming.py`
- Modify: `pa_agent/research_2d/parallel.py`
- Test: `tests/research_2d/test_streaming.py`
- Test: `tests/research_2d/test_parallel.py`

**Interfaces:**
- Produces: optional `progress_callback(processed_minutes: int, minute_utc_ms: int)` on `run_streaming_paths`; `current_rss_bytes()` and `peak_rss_bytes()`.

- [ ] **Step 1: Write failing heartbeat and RSS tests**

```python
def test_streaming_reports_monotonic_progress(production_fixture):
    progress = []
    run_streaming_paths(*production_fixture, progress_callback=lambda n, t: progress.append((n, t)))
    assert progress == sorted(progress)
    assert progress[-1][0] == production_fixture.expected_minutes

def test_rss_measurements_are_positive():
    assert current_rss_bytes() > 0
    assert peak_rss_bytes() >= current_rss_bytes()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/research_2d/test_streaming.py tests/research_2d/test_parallel.py -q`

Expected: FAIL because the callback and RSS functions are absent.

- [ ] **Step 3: Add bounded progress callbacks and platform RSS readers**

Emit progress at start, every 10,000 input minutes, and terminal completion. On Windows call `GetProcessMemoryInfo` through `ctypes` for current and peak working set; on POSIX use `/proc/self/statm` for current RSS and `resource.getrusage` for peak RSS. No third-party dependency is added.

- [ ] **Step 4: Verify tests and commit**

Run: `python -m pytest tests/research_2d/test_streaming.py tests/research_2d/test_parallel.py -q`

```powershell
git add pa_agent/research_2d/streaming.py pa_agent/research_2d/parallel.py tests/research_2d
git commit -m "feat(research-2d): expose worker progress and RSS"
```

### Task 3: Fail-closed orchestrator, watchdog, Ctrl+C, and output lock

**Files:**
- Modify: `pa_agent/research_2d/parallel.py`
- Modify: `pa_agent/research_2d/runner.py`
- Modify: `scripts/run_2d_baseline_evaluation.py`
- Test: `tests/research_2d/test_parallel.py`
- Test: `tests/research_2d/test_runner.py`

**Interfaces:**
- Produces: `run_tasks(tasks, *, max_workers, task_timeout_seconds, no_progress_timeout_seconds)`, `ParallelEvaluationError`, and `exclusive_output_lock(output_root)`.

- [ ] **Step 1: Write failing success-order, exception, timeout, no-progress, interrupt, and lock tests**

```python
def test_completion_order_does_not_change_registry_order():
    results = run_tasks(out_of_order_fixture, max_workers=2, task_timeout_seconds=30, no_progress_timeout_seconds=10)
    assert tuple(item.key for item in results) == tuple(item.key for item in out_of_order_fixture)

@pytest.mark.parametrize("mode", ["exception", "timeout", "no_progress", "keyboard_interrupt"])
def test_failure_modes_publish_nothing(mode, failure_fixture, tmp_path):
    with pytest.raises(ParallelEvaluationError) as caught:
        failure_fixture(mode, tmp_path)
    assert caught.value.task_key
    assert caught.value.traceback_text
    assert not list(tmp_path.glob("[!.]*"))

def test_output_lock_is_exclusive(tmp_path):
    with exclusive_output_lock(tmp_path):
        with pytest.raises(OutputRootLockedError):
            with exclusive_output_lock(tmp_path):
                pass
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/research_2d/test_parallel.py tests/research_2d/test_runner.py -q`

- [ ] **Step 3: Implement explicit spawn pool and fail-closed lifecycle**

Validate worker counts against `{1, 2, 6}`. Construct `ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context("spawn"))`. Observe futures through `as_completed(..., timeout=1)`; drain Manager-queue heartbeats, update per-key last-progress and RSS state, and enforce both deadlines. On any failure capture `traceback.format_exc()`, cancel all futures, terminate live worker processes, shut down with `cancel_futures=True`, remove the experiment temporary directory, and raise `ParallelEvaluationError` before reporting code runs.

- [ ] **Step 4: Add CLI flags and retain the existing main guard**

```python
parser.add_argument("--max-workers", type=int, choices=(1, 2, 6), default=1)
parser.add_argument("--task-timeout-seconds", type=int, default=28_800)
parser.add_argument("--no-progress-timeout-seconds", type=int, default=600)
```

Pass these values into `run_baseline_evaluation`; keep `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 5: Verify focused tests and commit**

Run: `python -m pytest tests/research_2d/test_parallel.py tests/research_2d/test_runner.py -q`

```powershell
git add pa_agent/research_2d/parallel.py pa_agent/research_2d/runner.py scripts/run_2d_baseline_evaluation.py tests/research_2d
git commit -m "feat(research-2d): fail closed parallel orchestration"
```

### Task 4: Parent-only publication and canonical/diagnostic separation

**Files:**
- Modify: `pa_agent/research_2d/runner.py`
- Test: `tests/research_2d/test_runner.py`

**Interfaces:**
- Produces: canonical 13-file artifact set unchanged in authority; separate `artifacts/research_2d_diagnostics/<experiment-id>/<run-id>.json` records outside the canonical experiment directory.

- [ ] **Step 1: Write failing canonical stability test**

```python
def test_runtime_diagnostics_do_not_change_canonical_hashes(serial_result, parallel_result):
    assert serial_result.authoritative_hashes == parallel_result.authoritative_hashes
    assert serial_result.diagnostics["worker_count"] == 1
    assert parallel_result.diagnostics["worker_count"] == 6
    assert serial_result.canonical_directory_files == parallel_result.canonical_directory_files
    assert serial_result.diagnostic_path.parent != serial_result.canonical_path
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/research_2d/test_runner.py -q`

- [ ] **Step 3: Refactor parent preparation, ordered collection, and publication**

Prepare all nine tasks before starting the pool. After `run_tasks` returns, reconstruct `all_runs` and `all_metrics` from the formal registry, then execute the existing confidence, conclusion, authority reconciliation, CSV, canonical JSON, report hash, and atomic `os.replace` logic. Write runtime timing/PID/worker/RSS/serialization fields to a separate diagnostics root after canonical publication; exclude that file and its run ID from `result_manifest.json`, the canonical experiment directory, and the computational experiment ID.

- [ ] **Step 4: Verify tests and commit**

Run: `python -m pytest tests/research_2d -q`

```powershell
git add pa_agent/research_2d/runner.py tests/research_2d/test_runner.py
git commit -m "refactor(research-2d): publish parallel results in parent"
```

### Task 5: Exact serial/parallel economic equivalence and fault matrix

**Files:**
- Create: `scripts/run_2d_parallel_capacity.py`
- Create: `tests/research_2d/test_parallel_acceptance.py`
- Modify: `tests/research_2d/test_parallel.py`

**Interfaces:**
- Consumes: the real short approved-data fixture and `run_tasks` with worker counts 1, 2, 6.

- [ ] **Step 1: Add an exact projection helper and failing acceptance tests**

```python
def economic_projection(result):
    return {
        "candidates": result.candidates,
        "trades": result.trades,
        "fills": tuple((f.action, f.event_time_utc_ms, f.quantity, f.fill_price, f.fee) for f in result.fills),
        "slippage": result.metrics["slippage"],
        "funding": tuple(t.funding for t in result.trades),
        "pnl": tuple(t.net_pnl for t in result.trades),
        "equity": result.daily_equity_points,
        "rejections": result.execution_rejections,
        "metrics": result.metrics,
        "conclusion": result.conclusion,
    }

def test_serial_two_and_six_worker_economics_are_exact(real_fixture):
    serial = real_fixture(max_workers=1)
    two = real_fixture(max_workers=2)
    six = real_fixture(max_workers=6)
    assert economic_projection(serial) == economic_projection(two) == economic_projection(six)
```

- [ ] **Step 2: Verify RED, implement any missing result projection only, and rerun**

Run: `python -m pytest tests/research_2d/test_parallel_acceptance.py -q`

Expected final result: serial, 2-worker, and 6-worker projections match exactly for Candidate identities, every fill/trade field, fee, inferred slippage, funding, PnL, equity sequence, rejections/skip reasons, metrics, and conclusion.

- [ ] **Step 3: Run the complete fault matrix**

Run: `python -m pytest tests/research_2d/test_parallel.py -q`

Expected: exception, timeout, no-progress, KeyboardInterrupt, duplicate lock, and temporary cleanup tests pass.

- [ ] **Step 4: Commit**

```powershell
git add scripts/run_2d_parallel_capacity.py tests/research_2d/test_parallel.py tests/research_2d/test_parallel_acceptance.py pa_agent/research_2d
git commit -m "test(research-2d): prove parallel economic equivalence"
```

### Task 6: Real-scale capacity gate and formal double evaluation

**Files:**
- Create at runtime: `artifacts/research_2d_capacity/capacity_report.json`
- Create at runtime: `artifacts/research_2d/<experiment-id>/`
- Create at runtime: `artifacts/research_2d/repro/<experiment-id>/`

**Interfaces:**
- Consumes: approved historical data root and the completed runner.
- Produces: measured worker decision, two formal artifact sets, and byte-hash comparison.

- [ ] **Step 1: Run real fixtures with 1, 2, and 6 workers**

```powershell
python scripts/run_2d_parallel_capacity.py --data-root artifacts/historical_data_readiness --workers 1 2 6 --output artifacts/research_2d_capacity/capacity_report.json
```

Expected: report contains parent peak RSS, each worker peak RSS, aggregate peak RSS, payload pickle bytes, result pickle bytes, elapsed seconds, no-progress maximum, and pass/fail for every worker count.

- [ ] **Step 2: Select the highest safe measured worker count**

Require aggregate peak RSS plus a 25% safety margin to remain below available physical memory observed before launch, no worker failure, and no-progress interval below the watchdog. Record the selected value; do not assume six.

- [ ] **Step 3: Run all regression and static gates**

```powershell
python -m pytest tests/research_2d -q
python -m pytest tests/research_cli -q
python -m pytest tests/research_data -q
python -m pytest tests/research_backtest -q
python scripts/validate_2b_test_registry.py
ruff check pa_agent/research_2d tests/research_2d scripts/run_2d_baseline_evaluation.py
ruff format --check pa_agent/research_2d tests/research_2d scripts/run_2d_baseline_evaluation.py
git diff --check fork/main...HEAD
python -m compileall -q pa_agent
```

Expected: no new failures and no changes under `pa_agent/research_backtest`.

- [ ] **Step 4: Run the first full formal evaluation**

```powershell
$workers = (Get-Content artifacts/research_2d_capacity/capacity_report.json -Raw | ConvertFrom-Json).selected_workers
python scripts/run_2d_baseline_evaluation.py --data-root artifacts/historical_data_readiness --output-root artifacts/research_2d --max-workers $workers
```

Expected: one atomically published 64-hex experiment directory and a separate runtime diagnostic record.

- [ ] **Step 5: Run the independent reproduction**

```powershell
$workers = (Get-Content artifacts/research_2d_capacity/capacity_report.json -Raw | ConvertFrom-Json).selected_workers
python scripts/run_2d_baseline_evaluation.py --data-root artifacts/historical_data_readiness --output-root artifacts/research_2d/repro --max-workers $workers
```

Expected: same 64-hex experiment ID.

- [ ] **Step 6: Compare every authoritative artifact hash**

Read both `result_manifest.json` files and require exact equality of `file_sha256`; compare every listed file byte-for-byte. Report runtime diagnostics separately and permit only diagnostic differences.

- [ ] **Step 7: Final safety and repository checks**

Confirm clean worktree, no related Python/GUI process, no API keys, no HTTP/trading interface, no 2D scope violation, no 2D publication lock, and no start of 2E or live/paper execution.
