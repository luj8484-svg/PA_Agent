# Second-Batch 2C Final Source Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six PR #4 review blockers without changing the trading strategy, adding 2D, or introducing GUI, LLM, API-key, network, or order capability.

**Architecture:** Preserve the existing deterministic 2A/2B/2C modules and add only narrow boundaries: one CPython runtime guard, one rejection-policy reducer, explicit mark-based valuation, transactional entry-batch rehearsal, verifiable run identity, and a production evidence catalog/bridge. Rename the existing Timeline metadata as a registry and add six independently content-addressed full Golden cases.

**Tech Stack:** CPython 3.12.13, frozen slotted dataclasses, Decimal, canonical JSON/SHA-256, pytest, Hypothesis, Ruff.

## Global Constraints

- `DETERMINISTIC_RESEARCH_RUNTIME_V1 = CPython 3.12.13`; do not weaken the 2A 0-ULP/runtime identity contract.
- `pa-research --help` remains usable on other runtimes, but Candidate, Plan, Simulation, and deterministic backtest execution fail closed before partial output.
- PR #4 remains Draft; do not merge `main` and do not start 2D.
- No API Key, GUI, LLM, HTTP/socket, authenticated exchange endpoint, `create_order`, paper/live automation, or performance analytics.
- All behavioral changes use RED → GREEN tests. Existing 2B formulas and Candidate/Plan canonical identities remain unchanged.

---

### Task 1: Deterministic research runtime guard

**Files:**
- Create: `.python-version`
- Create: `pa_agent/research_backtest/runtime.py`
- Modify: `pa_agent/research_cli.py`
- Modify: `pa_agent/research_backtest/strategy/candidate_factory.py`
- Modify: `pa_agent/research_backtest/planning/factory.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Modify: `docs/research_cli.md`
- Modify: the four 2C documents under `docs/superpowers/`
- Test: `tests/research_cli/test_research_cli.py`
- Test: `tests/research_backtest/unit/test_versions_numeric_canonical.py`
- Test: `tests/research_backtest/simulation/test_domain_identity_scope.py`

**Interfaces:**
- Produces: `assert_deterministic_research_runtime() -> None`, `runtime_status() -> ResearchRuntimeStatus`.
- Consumes: `platform.python_implementation()` and `sys.version_info[:3]` only; no wall-clock/network input.

- [ ] Add tests that patch runtime facts to CPython 3.12.12, CPython 3.12.13, and PyPy 3.12.13; expect explicit failure except for CPython 3.12.13.
- [ ] Run the focused tests and confirm RED because the formal guard and CLI fields do not exist.
- [ ] Implement `DETERMINISTIC_RESEARCH_RUNTIME_V1`, exact implementation/version validation, and the CLI lines `implementation=CPython`, `version=3.12.13`, `status=PASS`.
- [ ] Guard Candidate, Plan, and Simulation public execution boundaries before any output/state mutation; leave help/version parsing unguarded.
- [ ] Update runtime documentation and `.python-version` to `3.12.13`; run focused tests to GREEN.

### Task 2: ExecutionRejection disposition reducer

**Files:**
- Create: `pa_agent/research_backtest/simulation/rejections.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Modify: `pa_agent/research_backtest/simulation/planning.py`
- Test: `tests/research_backtest/simulation/test_rejection_policy.py`
- Test: `tests/research_backtest/simulation/test_dynamic_planning.py`

**Interfaces:**
- Produces: `apply_rejection_policy(rejections, stage, subject_kind) -> RejectionPolicyOutcome` where action is `CONTINUE`, `PATH_INVALID`, or `EXPERIMENT_INVALID` and the invalid reason contains rejection ID, reason, disposition, and stage.
- Consumes: the frozen `ExecutionRejection.disposition`; never re-derives disposition from reason.

- [ ] Add table tests for contract, cost, funding schedule, data-invalid, below-min-quantity, and scheduled-exit cancellation dispositions.
- [ ] Add a batch regression in which one accepted plan and one path-invalid rejection must yield zero fills and INVALID.
- [ ] Run focused tests and confirm RED because the current engine merely stores entry rejections.
- [ ] Implement the pure policy reducer and apply it at Candidate→Intent, sizing/scaling/entry-plan, and exit-plan boundaries.
- [ ] Verify candidate rejection continues without Fill, while path/experiment invalidation is immediate and preserves all rejection evidence.

### Task 3: Mark-evidence valuation and peak-equity correction

**Files:**
- Modify: `pa_agent/research_backtest/simulation/ledger.py`
- Modify: `pa_agent/research_backtest/simulation/fills.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Test: `tests/research_backtest/simulation/test_ledger_account.py`
- Test: `tests/research_backtest/simulation/test_fills_positions.py`

**Interfaces:**
- `reduce_ledger()` mutates wallet/locks/reserves/consumed ledger IDs only and preserves the prior equity/peak valuation fields.
- `mark_positions_equity(state, positions, current_marks) -> EngineState` is the only normal valuation boundary.
- `apply_exit_fill(..., remaining_unrealized_pnl=...)` recomputes equity from wallet plus all remaining positions and never promotes stale equity to peak.

- [ ] Add RED regressions for profitable single-position exit, BTC close with losing ETH retained, funding income with stale unrealized PnL, and partial multi-position close.
- [ ] Remove peak updates from ledger reduction and unconditional unrealized reset from exit fill.
- [ ] At each frozen valuation stage compute all-position unrealized PnL from the current minute’s explicit mark evidence and then update equity/peak.
- [ ] Run focused and full simulation tests to GREEN, proving `equity == wallet + remaining unrealized` after every partial close.

### Task 4: Transactional entry-batch commit

**Files:**
- Modify: `pa_agent/research_backtest/simulation/fills.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Test: `tests/research_backtest/simulation/test_entry_batch_atomicity.py`

**Interfaces:**
- Produces: `apply_entry_batch(state, plans) -> EntryBatchCommit | EntryBatchCommitFailure`.
- The success object contains the final state, all fills, all ledger entries, and positions; failure contains `ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION` and leaves the original canonical state unchanged.

- [ ] Add RED tests for second-plan failure, duplicate symbol, duplicate plan ID, negative available balance, evidence mismatch, and valid BTC/ETH all-at-once commit.
- [ ] Build every fill/position/ledger tuple first, replay the stable-order batch against a temporary immutable state, and validate all invariants.
- [ ] Catch `AccountInvariantError`, `LedgerReplayError`, duplicate/evidence `ValueError`, and return fail-closed evidence instead of escaping the run.
- [ ] Replace the engine’s per-plan mutation loop with the single transactional call; run focused tests to GREEN.

### Task 5: Bind input identity to run and output

**Files:**
- Modify: `pa_agent/research_backtest/simulation/identity.py`
- Modify: `pa_agent/research_backtest/simulation/inputs.py`
- Modify: `pa_agent/research_backtest/simulation/domain.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Modify: `pa_agent/research_backtest/simulation/output.py`
- Test: `tests/research_backtest/simulation/test_domain_identity_scope.py`
- Test: `tests/research_backtest/simulation/test_minute_engine_output.py`

**Interfaces:**
- `SimulationInputIdentity` references canonical manifests/evidence objects and verifies each stored content hash against the actual input object.
- `SimulationResult` contains `simulation_run_id`, input identity/hash, config ID/hash, and paths.
- `OutputManifest` contains run/input/config/result hashes, per-file hashes, path count, and minute count.

- [ ] Add RED tests for acquisition-time independence, every material stream hash changing the run ID, identical economics from different inputs retaining different IDs, and external-identity tampering failing closed.
- [ ] Add `StateSnapshot` and persist `state_snapshots.jsonl` for every processed minute and terminal INVALID.
- [ ] Make `run_simulation()` validate identity against actual trade/mark/funding/Candidate/contract/cost/funding-risk/maintenance inputs before path construction.
- [ ] Bind all required identity fields into result and manifest; run focused output/identity tests to GREEN.

### Task 6: Production evidence bridge

**Files:**
- Create: `pa_agent/research_backtest/simulation/evidence.py`
- Modify: `pa_agent/research_backtest/simulation/planning.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Test: `tests/research_backtest/simulation/test_production_evidence_bridge.py`

**Interfaces:**
- Produces: `SimulationEvidenceCatalog`, `build_planning_evidence_from_engine(...)`, and `build_entry_batch_inputs_from_engine(...)`.
- `production_planner_dependencies(catalog, config)` uses the production bridge by default and no longer accepts an opaque entry-input factory.

- [ ] Add RED tests that account evidence is replayed from the current `EngineState`, BTC/ETH share one snapshot, no future slice is accepted, and no sizing/scaling/plan result can be injected.
- [ ] Implement catalog lookup for Candidate, target-open, contract, cost, funding schedule/risk, account/open-risk/position, and version/split evidence.
- [ ] Wire the bridge into the production dependency constructor while retaining explicitly labelled local fixture dependencies only in tests.
- [ ] Add one complete real Candidate→Intent→2B planning→entry→exit→ledger→trade→equity→PathResult→OutputManifest integration and run it GREEN without fake plans or injected sizing/scaling.

### Task 7: Timeline Registry and six real Canonical Goldens

**Files:**
- Rename: `tests/research_backtest/simulation/fixtures/timeline_golden_v1.json` to `timeline_registry_v1.json`
- Create: `tests/research_backtest/simulation/fixtures/timeline_full_goldens_v1.json`
- Modify: `tests/research_backtest/simulation/test_acceptance_registry.py`
- Modify: `tests/research_backtest/simulation/test_minute_engine_output.py`
- Modify: 2C acceptance/red-team/plan/spec documents.

**Interfaces:**
- Registry: 24 traceability entries, never called Golden fixtures.
- Full Golden file: six cases, each containing input fixture, event-sequence, ledger, fill/trade, equity, and PathResult canonical SHA-256 values.

- [ ] Add RED schema/count/content-hash tests and explicit TL-05, TL-18, TL-19, and TL-22 semantic assertions.
- [ ] Generate the six expected hashes only from reviewed canonical fixture construction and freeze them in the Golden file.
- [ ] Update documents and registry tests to report exactly `24 Timeline Registry entries` and `6 full Canonical Goldens`.
- [ ] Run Golden, Timeline, and complete-run tests to GREEN.

### Task 8: CPython 3.12.13 verification, scope audit, and Draft PR update

**Files:**
- Modify only verification evidence/PR text if needed; no production semantics.

- [ ] Install or provision official CPython 3.12.13 and create an isolated validation environment.
- [ ] Run `python --version`, editable dev installation, CLI validation, research_cli/data/execution/simulation/full research_backtest, registry validator, Ruff check/format, diff check, and compileall exactly as requested.
- [ ] Run forbidden-capability scans and confirm no 2D, GUI, LLM, key, network, account mutation beyond simulation, or trading interface was added.
- [ ] Review `git diff 092f72d44d59659de887536ebdb8a0e8906afb7a...HEAD`, commit intentionally, push the existing branch, and update PR #4 body with exact counts and any actual failure.
- [ ] Confirm PR #4 is Draft/Open/unmerged and stop for final source review.

## Self-review

- Spec coverage: all six blockers map one-to-one to Tasks 1–7; Task 8 covers every requested verification and PR constraint.
- Placeholder scan: no deferred implementation placeholders remain.
- Type consistency: runtime, rejection, valuation, transactional batch, identity, evidence bridge, result, and manifest interfaces have single owners and explicit consumers.
