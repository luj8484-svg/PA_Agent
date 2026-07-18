# 2C Final Boundary Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining production evidence, run identity/stage, and GitHub Actions blockers without changing accepted 2A/2B/2C economics.

**Architecture:** Convert production evidence lookup failures into typed planning results consumed by the existing rejection reducer, bind the computational experiment and recomputed frozen identities into the simulation run identity, and restrict production contexts to BACKTEST. Keep the workflow research-only and expose each required command as a separate Windows Actions step.

**Tech Stack:** CPython 3.12.13, frozen dataclasses, Canonical JSON/SHA-256 identities, pytest, Ruff, GitHub Actions.

## Global Constraints

- PR #4 remains Draft and is not merged into `main`.
- No 2D, GUI, LLM, API key, HTTP, exchange trading endpoint, `create_order`, or automatic order capability.
- Do not change exit-batch atomicity, Ledger economics, Stop/TP selection, Golden economics, 2A/2B formulas, or Candidate/Plan business semantics.
- Every production behavior change follows RED → GREEN.

---

### Task 1: Production planning fail-closed boundary

**Files:**
- Modify: `pa_agent/research_backtest/simulation/evidence.py`
- Modify: `pa_agent/research_backtest/simulation/planning.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Test: `tests/research_backtest/simulation/test_production_evidence_fail_closed.py`

**Interfaces:**
- Consumes: real `ExitIntent`, `EngineState`, `SimulationEvidenceCatalog`, existing 2B planners and rejection reducer.
- Produces: typed production-evidence failure or legal planning inputs that yield `ExecutionRejection`, then `PathInvalidEvent` and an INVALID path.

- [ ] Add real production-run tests for changed exit quantity/side, missing or duplicate target-open/contract/cost evidence, and entry evidence failures.
- [ ] Run the focused tests and confirm expected ValueError escapes or missing typed results.
- [ ] Add narrow production evidence error/result types and remove the early exit-quantity ValueError.
- [ ] Convert only known evidence failures into formal rejection/path-invalid outputs; do not catch `Exception`.
- [ ] Re-run the focused tests and existing scheduled-exit/production-bridge suites to green.

### Task 2: Run identity and BACKTEST stage closure

**Files:**
- Modify: `pa_agent/research_backtest/simulation/identity.py`
- Modify: `pa_agent/research_backtest/simulation/context.py`
- Modify: `pa_agent/research_backtest/simulation/engine.py`
- Test: `tests/research_backtest/simulation/test_production_run_context.py`

**Interfaces:**
- Consumes: `computational_experiment_id`, actual config/catalog/execution objects, frozen 2A/2B/2C constants.
- Produces: experiment-bound `SimulationInputIdentity`, different `simulation_run_id` across experiments, actual-object identity validation, and BACKTEST-only production dependencies.

- [ ] Add failing tests for experiment identity variation/determinism, PAPER/LIVE rejection, and internally self-consistent forged identity hashes.
- [ ] Verify the focused tests fail for the missing experiment field and trusted declarations.
- [ ] Bind and validate the experiment SHA-256, recompute all expected identity hashes during every validation, and carry the validated stage in dependencies.
- [ ] Re-run focused and full identity/context tests to green.

### Task 3: Research-only GitHub Actions and final verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: PR #4 body after the pushed commit exists.

**Interfaces:**
- Produces: `workflow_dispatch` plus one Actions step per required CPython 3.12.13 research command.

- [ ] Add `workflow_dispatch` and split all required commands into independent steps.
- [ ] Run the exact local CPython 3.12.13 install, test, registry, Ruff, diff-check, and compile matrix.
- [ ] Commit and fast-forward push the reviewed branch; verify local and remote heads match.
- [ ] Query or manually trigger the workflow when authorized, record run ID/URL/status/conclusion, and truthfully update the Draft PR body.

## Self-Review

- Spec coverage: the two source blockers, CI blocker, thirteen report items, and all prohibited scopes map to Tasks 1–3.
- Placeholder scan: no deferred implementation markers are present.
- Type consistency: evidence failures terminate through the existing rejection policy; run identity is constructed and verified from the same experiment/config/catalog objects.
