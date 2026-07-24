# Data Materiality Reclassification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reclassify the existing official Binance historical dataset by economic materiality without redownloading data or running full 2D.

**Architecture:** Add a read-only audit module that reuses immutable Canonical files, reconstructs every native-versus-aggregated discrepancy, classifies price versus audit-only fields, computes a V2 pre-roll identity, and evaluates mark-gap scope. A thin script writes deterministic artifacts and derives the final readiness status from explicit gates.

**Tech Stack:** Python 3.12.13, Decimal, existing Canonical hashing, existing 2A pure strategy functions, pytest.

## Global Constraints

- Do not download historical data.
- Do not modify 2A, 2B, or 2C production modules.
- Do not run full 2D or create trading/account/API-key capability.
- Official native 4H/1D is authoritative for 2A; trade 1m aggregation is audit-only.
- No mark interpolation, index substitution, or forward fill.

---

### Task 1: Materiality classification primitives

**Files:**
- Create: `pa_agent/research_data/materiality_audit.py`
- Test: `tests/research_data/test_materiality_audit.py`

**Interfaces:**
- Produces deterministic field differences, split classification, bar hashes, pre-roll identity and readiness classification.

- [ ] Write tests for audit-only/price classifications, absolute/relative differences, split boundaries, 274-bar pre-roll hash, and readiness gates.
- [ ] Run the focused tests and confirm they fail because the module is absent.
- [ ] Implement the smallest pure functions needed by the tests.
- [ ] Run focused tests until green.

### Task 2: Existing-data audit runner

**Files:**
- Create: `scripts/audit_historical_materiality.py`
- Modify: `.gitignore`
- Test: `tests/research_data/test_materiality_audit.py`

**Interfaces:**
- Consumes immutable data under `artifacts/historical_data_readiness/data/`.
- Produces the seven required materiality artifacts.

- [ ] Add a failing integration test using tiny Canonical fixtures and a frozen gap report.
- [ ] Verify the integration test fails for the missing runner.
- [ ] Implement full issue reconstruction, mark-gap analysis and report serialization without network imports.
- [ ] Run the focused test and verify the generated identities and status.

### Task 3: Execute and verify the audit

**Files:**
- Write: `artifacts/historical_data_readiness/native_bar_materiality.jsonl`
- Write: `artifacts/historical_data_readiness/native_bar_materiality_summary.json`
- Write: `artifacts/historical_data_readiness/candidate_materiality_report.json`
- Write: `artifacts/historical_data_readiness/mark_gap_materiality.json`
- Write: `artifacts/historical_data_readiness/experiment_split_candidate_v2.json`
- Write: `artifacts/historical_data_readiness/final_materiality_report.json`
- Write: `artifacts/historical_data_readiness/final_materiality_report.md`

**Interfaces:**
- Produces the final evidence package; does not mutate source Canonical data.

- [ ] Run the audit against the existing D-drive dataset and record exact bar/field counts.
- [ ] Verify all required artifacts, hashes and authority-policy fields.
- [ ] Run `pytest tests/research_data -q`, Ruff, format check, compileall and `git diff --check`.
- [ ] Confirm no 2A/2B/2C path changed, no network access occurred, no 2D ran and no related process remains.
