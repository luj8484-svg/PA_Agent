# Second Batch 2C Final Integration Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three remaining 2C source blockers and two acceptance issues without changing strategy semantics or entering 2D.

**Architecture:** Add one immutable `ProductionRunContext` as the only production dependency source, bind its canonical identities into `SimulationInputIdentity`, and keep the lower-level engine callable only for isolated tests. Scheduled exits use a versioned execution-geometry projection; all economic mutations are followed by a single explicit valuation commit, while same-stage exits rehearse and commit atomically. Canonical Goldens are produced by the real engine and CI runs the frozen research-only matrix on CPython 3.12.13.

**Tech Stack:** CPython 3.12.13, frozen dataclasses, Decimal accounting, canonical JSON/SHA-256 identities, pytest, Ruff, GitHub Actions.

## Global Constraints

- PR #4 remains Draft and must not be merged into `main`.
- Do not implement 2D, GUI, LLM, API keys, HTTP clients, exchange authentication, trading endpoints, or automatic orders.
- Production Candidate/Plan/Simulation execution must fail closed outside CPython 3.12.13.
- Tests must be written and observed failing before production changes.
- Economic output must remain deterministic and use only event/market clocks.

---

### Task 1: Production Run Context and identity closure

**Files:**
- Create: `pa_agent/research_backtest/simulation/context.py`
- Modify: `pa_agent/research_backtest/simulation/identity.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Modify: `pa_agent/research_backtest/simulation/versions.py`
- Test: `tests/research_backtest/simulation/test_production_run_context.py`

**Interfaces:**
- Produces: `ProductionRunContext`, `RunConfigurationMismatch`, `make_production_run_context(...)`, `build_production_engine_dependencies(context)`, and `run_production_simulation(inputs, context)`.
- Consumes: `SimulationConfig`, `SimulationEvidenceCatalog`, Candidate tuple, `ExecutionTimeConfig`, and `SimulationInputIdentity` built from the actual inputs/catalog/context.

- [ ] Write tests that intentionally mismatch code/dependency identities, ExecutionTimeConfig hash, catalog identity, Candidate tuple, target-open/watermark content, factory catalog binding, and 2A/2B/2C versions.
- [ ] Run `pytest tests/research_backtest/simulation/test_production_run_context.py -v` and verify failures show the missing context/validation behavior.
- [ ] Implement the immutable context and one constructor; compute Candidate, target-open, watermark, catalog, execution-time, planner, and engine hashes from actual objects.
- [ ] Make the production wrapper validate the complete context before creating any path; raise `RunConfigurationMismatch` without partial results.
- [ ] Extend `SimulationInputIdentity` with the new actual identity fields and verify target-open/watermark changes alter the run ID.
- [ ] Re-run the focused tests and the existing production bridge tests until green.

### Task 2: Scheduled Exit execution-position projection

**Files:**
- Modify: `pa_agent/research_backtest/simulation/positions.py`
- Modify: `pa_agent/research_backtest/simulation/planning.py`
- Modify: `pa_agent/research_backtest/simulation/evidence.py`
- Test: `tests/research_backtest/simulation/test_scheduled_exit_production.py`

**Interfaces:**
- Produces: `ExitExecutionPositionSnapshot` with version `EXIT_EXECUTION_POSITION_SNAPSHOT_V1` and `exit_execution_position_snapshot(position)`.
- The snapshot contains only `position_id`, origins, symbol, side, and quantity; funding counters/reserves/deltas are excluded.

- [ ] Write failing tests for funding-preserved scheduled exit, changed quantity rejection, and an already-closed position cancelling the pending exit without invoking the planner.
- [ ] Verify the tests fail because the current bridge reuses `intent.position_snapshot_hash`.
- [ ] Store the projection hash when creating the ExitCondition/ExitIntent and recompute the current projection hash in `build_exit_inputs_from_engine`.
- [ ] Pass the recomputed hash to the real 2B Exit Planner so changed geometry produces `POSITION_SNAPSHOT_CHANGED` while funding-only mutations do not.
- [ ] Add a complete real Candidate → Entry → Funding → TIME_EXIT → real ExitPlan → Fill/Trade/Ledger/Equity/PathResult integration test and rerun focused tests.

### Task 3: Valuation commit and atomic same-stage exits

**Files:**
- Modify: `pa_agent/research_backtest/simulation/ledger.py`
- Modify: `pa_agent/research_backtest/simulation/fills.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Modify: `pa_agent/research_backtest/simulation/output.py`
- Test: `tests/research_backtest/simulation/test_terminal_valuation_consistency.py`
- Test: `tests/research_backtest/simulation/test_exit_batch_atomicity.py`

**Interfaces:**
- Produces: `assert_account_snapshot_consistent(state)`, explicit `commit_valuation(state, unrealized_pnl)`, and an all-or-none exit-batch rehearsal/commit result.

- [ ] Write failing terminal-state tests for funding then maintenance failure, entry then intraminute evidence failure, and every persisted StateSnapshot.
- [ ] Write failing order-reversal tests for two scheduled-open exits and two intraminute exits, including fees/slippage and failure of the second exit.
- [ ] Keep `reduce_ledger` limited to wallet/locks/reserves/consumed IDs; use one explicit mark basis to value the entire post-stage state exactly once.
- [ ] Rehearse all same-stage Exit Fill/Ledger/Position changes on immutable temporary state and commit only when all succeed; on failure emit evidence and invalidate without partial fill/ledger/peak changes.
- [ ] Set `PathResult.entry_disabled` from `halt_trigger_time_utc_ms is not None` and assert consistency before every minute return and output snapshot write.
- [ ] Run both focused test files and the existing ledger/fill/minute-engine suites until green.

### Task 4: Full Stop/TP Engine Golden and research CI

**Files:**
- Modify: `tests/research_backtest/simulation/test_triggers_ambiguity_halt.py`
- Modify: `tests/research_backtest/simulation/fixtures/timeline_full_goldens_v1.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/superpowers/reviews/second-batch-2c-acceptance-matrix.md`

**Interfaces:**
- Produces: one full real-engine ambiguity Golden where BASELINE chooses TP and CONSERVATIVE chooses STOP with distinct fills, trade PnL, equity, and PathResult hashes.

- [ ] Replace the component-only ambiguity assertion with a held-position engine run whose trade low/high crosses stop/TP but not liquidation.
- [ ] Observe the Golden mismatch/failure before changing the frozen JSON.
- [ ] Freeze the six canonical hashes from actual engine outputs and verify all six scenarios are full Engine Goldens.
- [ ] Expand CPython 3.12.13 CI to run environment validation, research CLI/data/backtest tests, the 2B registry validator, Ruff check/format, and compileall; exclude GUI/legacy E2E.
- [ ] Run the focused Golden/registry tests and inspect workflow YAML.

### Task 5: Complete verification, publication, and Draft PR metadata

**Files:**
- Modify: PR #4 body only after the remote commit exists.

- [ ] Run the exact CPython 3.12.13 install, environment, pytest, registry, Ruff, diff-check, compileall, and scope/security commands required by the review.
- [ ] Confirm `pytest tests/research_backtest -q` reports zero failures and record exact counts.
- [ ] Confirm the worktree diff contains no 2D/API/GUI/LLM/HTTP/trading capability.
- [ ] Commit the reviewed scope, push with ordinary fast-forward Git, and verify the remote head.
- [ ] Update PR #4 body with the new head, exact test counts, exact Golden classification, and truthful cloud workflow status while keeping it Draft.

## Self-Review

- Spec coverage: all three BLOCKERs, both acceptance issues, twelve requested report fields, and the no-2D/security boundary map to Tasks 1–5.
- Placeholder scan: no deferred implementation markers or unspecified error handling remain.
- Type consistency: production context owns config/catalog/Candidates/execution config/input identity; the engine wrapper consumes the same context, and scheduled exits share one versioned projection function at creation and execution.
