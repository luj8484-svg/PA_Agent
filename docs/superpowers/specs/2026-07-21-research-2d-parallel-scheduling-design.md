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

The parent process prepares immutable task payloads and derived reporting metadata. A bounded process pool executes at most six independent tasks concurrently. The worker calls the existing `_run_scenario` function; it does not implement an alternate engine or economic path. The parent collects results in the predeclared deterministic task order and then executes the existing metric, reconciliation, report, hash, and atomic-publication logic.

## Resource and safety boundaries

- Default maximum workers: six on this 16-logical-processor, 64 GiB host.
- No network, API key, account, GUI, LLM, order, or exchange-authentication capability is added.
- No files under `pa_agent/research_backtest` are modified.
- No 2D task writes shared mutable state while workers run.

## Verification

- Unit test the exact task registry, uniqueness, and deterministic ordering.
- Unit test ordered result reconstruction independently of completion order.
- Run the existing Research 2D suite, Ruff, format check, and diff check.
- Execute a short serial-versus-parallel fixture and compare canonical economic outputs.
- Run the full formal evaluation twice to separate ignored output roots and compare all artifact hashes.
