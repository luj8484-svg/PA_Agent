# Research 2D bounded parallel scheduling

## Purpose

Reduce wall-clock time for the already-approved 2D historical evaluation without changing its market data, Candidate stream, 2B planning, 2C minute economics, scenarios, metrics, or conclusion policy.

## Frozen behavior

- Each `(split, authority, scenario)` evaluation remains an isolated task.
- Inside each task, minutes and Baseline/Conservative paths retain the frozen deterministic order.
- Native primary and aggregated audit sensitivity remain distinct authorities.
- The task payload contains the same Candidates, trend evidence, market evidence, versions, hashes, and experiment identity used by the sequential runner.
- Returned results are reconciled by a fixed task key, never by process completion order.
- The final artifact directory is still committed atomically only after every required task succeeds.
- A worker exception aborts the run; partial results remain non-authoritative and are not promoted.

## Execution design

The parent process prepares immutable task payloads and derived reporting metadata. A bounded process pool executes at most six independent tasks concurrently. The pool uses an explicit cross-platform multiprocessing context; `spawn` is mandatory on Windows and supported on every platform. Worker entry points are module-level callables, the CLI runner has a `__main__` guard, and every payload and result must pass a pickle round trip before formal execution.

The worker calls the existing `_run_scenario` function; it does not implement an alternate engine or economic path. `max_workers` is configurable and accepts 1, 2, or 6. Worker bootstrap fixes `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` to one before numerical work begins.

The parent consumes futures with `as_completed` so a failure is observed immediately, but stores successful results by the predeclared task key and reconstructs the final collection exclusively in registry order. A worker exception, task timeout, no-progress watchdog breach, or `KeyboardInterrupt` records the affected task key and complete traceback, cancels pending futures, terminates the pool, and prevents metrics, reports, hashes, or publication. Temporary output remains non-authoritative and is removed during controlled failure handling.

Each task emits parent-observable progress heartbeats. The watchdog has separately configurable task-runtime and no-progress limits. Normal shutdown waits for all workers; failure and Ctrl+C shutdown cancel pending work and terminate remaining child processes. The runner holds an exclusive lock scoped to the formal output root from preflight through atomic publication, so a second runner cannot execute or publish concurrently.

## Resource and safety boundaries

- Default maximum workers: six on this 16-logical-processor, 64 GiB host.
- The formal worker count is selected only after measuring parent RSS, per-worker peak RSS, aggregate peak RSS, and serialized payload/result sizes on a real-scale task with 1, 2, and 6 workers.
- No network, API key, account, GUI, LLM, order, or exchange-authentication capability is added.
- No files under `pa_agent/research_backtest` are modified.
- Workers only read immutable input files. They do not share database connections, open file handles, module-level mutable caches, or output files.
- Only the parent writes the temporary artifact set and atomically publishes the final directory after every task succeeds.

## Canonical identity and diagnostics

Canonical economic artifacts contain no runtime diagnostics. Fields such as generation time, duration, PID, worker count, multiprocessing context, RSS, heartbeat times, and temporary paths are written only beneath a separate diagnostics root, never inside the canonical experiment directory, and are excluded from canonical artifact hashes. Repeated full runs with the same approved data, code, dependencies, and configuration must produce byte-identical authoritative economic artifacts regardless of worker count.

## Verification

- Unit test the exact task registry, uniqueness, and deterministic ordering.
- Unit test ordered result reconstruction independently of completion order.
- Test payload/result pickle round trips under the Windows-compatible `spawn` context.
- Test worker failure, task timeout, no-progress timeout, and `KeyboardInterrupt`; each must cancel pending work, identify the task key, preserve the full traceback, clean temporary state, and publish nothing.
- Run the existing Research 2D suite, Ruff, format check, and diff check.
- Execute the same real fixture with 1, 2, and 6 workers.
- Compare serial and parallel results trade by trade and point by point: Candidates; entry and exit fills; quantities; fees; slippage; funding; PnL; equity sequence; skip/rejection reasons; metrics; and conclusion.
- Measure serialized payload/result byte counts and parent, worker, and aggregate peak RSS for the real fixture. Select the formal worker count from the measurements and record the decision in diagnostics.
- Run the full formal evaluation twice to separate ignored output roots. Compare byte hashes for every authoritative economic artifact while separately retaining non-canonical runtime diagnostics.
