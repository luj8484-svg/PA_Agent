# Binance Data Readiness Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit, reconcile, and when stale incrementally refresh the existing BTCUSDT/ETHUSDT Binance USDⓈ-M public dataset before any 2D evaluation.

**Architecture:** A one-shot audit script reuses the allowlisted `BinancePublicClient`, canonical serialization, pagination, hashing, normalization, and gap detection already frozen in `research_data`. It discovers the latest completed local snapshot, writes a new immutable version directory for refreshed canonical data, reconciles deterministic samples against Binance, and emits seven machine-readable/human-readable readiness artifacts without importing strategy, execution, simulation, GUI, LLM, or authenticated exchange code.

**Tech Stack:** CPython 3.12.13, stdlib JSON/Decimal/datetime/hashlib, existing `pa_agent.research_data`, pytest, Ruff.

## Global Constraints

- Source host is exactly `https://fapi.binance.com`.
- Allowed paths are exactly `/fapi/v1/time`, `/fapi/v1/klines`, `/fapi/v1/markPriceKlines`, `/fapi/v1/indexPriceKlines`, `/fapi/v1/fundingRate`, and `/fapi/v1/exchangeInfo`.
- No API key, secret, signature, account endpoint, order endpoint, `create_order`, third-party market data, or generated missing market data.
- Do not modify 2A, 2B, 2C, strategy, planning, simulation, Ledger, event order, or Golden economics.
- Only fully closed klines may enter canonical output.
- Stale refresh creates a new version directory and never overwrites the selected source snapshot.
- The only final statuses are `READY_FOR_BASELINE_EVALUATION`, `STALE_DATA_REFRESH_REQUIRED`, `DATA_COVERAGE_INSUFFICIENT`, `DATA_INTEGRITY_FAILED`, and `SOURCE_UNAVAILABLE`.
- Do not start 2D, WebSocket, automatic trading, or a long-running service.

---

### Task 1: Freeze pure audit semantics

**Files:**
- Create: `scripts/audit_binance_data_readiness.py`
- Create: `tests/research_data/test_data_readiness_audit.py`

**Interfaces:**
- Consumes: canonical JSONL records and Binance server time in milliseconds.
- Produces: `latest_closed_boundaries(server_time_ms)`, `deterministic_sample(records, count, seed, namespace, timestamp_field)`, `merge_records(old, new, key_field)`, and `freshness_status(...)`.

- [ ] Write tests for exact 1m/4h/1d close boundaries, stable hash-ranked sampling, duplicate/conflict detection, and FRESH/STALE/SEVERELY_STALE thresholds.
- [ ] Run `python -m pytest tests/research_data/test_data_readiness_audit.py -v` and confirm RED because the audit module does not exist.
- [ ] Implement the minimal pure functions with integer UTC arithmetic and canonical comparisons.
- [ ] Re-run the focused test and confirm GREEN.

### Task 2: Discover and inventory existing snapshots

**Files:**
- Modify: `scripts/audit_binance_data_readiness.py`
- Test: `tests/research_data/test_data_readiness_audit.py`

**Interfaces:**
- Consumes: `--search-root` containing `summary.json`, `acquisition_manifest.json`, `manifests/*.json`, and `canonical/*.jsonl`.
- Produces: deterministic snapshot inventory, selected latest completed snapshot, per-symbol stream coverage, hashes, duplicate counts, unclosed counts, and UTC timestamps.

- [ ] Add fixture tests proving discovery selects the newest completed summary with a stable path tie-break and rejects incomplete canonical layouts.
- [ ] Implement streaming JSONL inspection without mutating source files.
- [ ] Verify local hashes against stored dataset manifests and record all gaps rather than globally invalidating mark/index data.

### Task 3: Public connectivity and incremental refresh

**Files:**
- Modify: `scripts/audit_binance_data_readiness.py`
- Test: `tests/research_data/test_data_readiness_audit.py`

**Interfaces:**
- Consumes: `BinancePublicClient`, selected local records, and latest fully closed boundaries.
- Produces: `artifacts/data_readiness/refreshed/<UTC-version>/` with merged canonical JSONL, per-dataset manifests, raw delta acquisition pages, current contract snapshot, and acquisition manifest.

- [ ] Add fake-client tests that assert every request remains on the six-path allowlist and that unclosed remote bars are rejected.
- [ ] Download only records after each local stream end through its own fully closed boundary.
- [ ] Merge by canonical primary key; fail on conflicting duplicates; recompute content hashes, gaps, record counts, and new-record counts.
- [ ] Save old and refreshed hashes and keep the source snapshot byte-for-byte unchanged.

### Task 4: Deterministic online reconciliation

**Files:**
- Modify: `scripts/audit_binance_data_readiness.py`
- Test: `tests/research_data/test_data_readiness_audit.py`

**Interfaces:**
- Consumes: refreshed canonical records and seed `20260719`.
- Produces: 30 trade-1m, 20 mark-1m, 10 native-4h, 10 native-1d, and 10 funding comparisons per symbol.

- [ ] Rank records by SHA-256 of `seed|symbol|dataset|timestamp` and persist the rule and seed.
- [ ] Re-fetch each selected timestamp through the matching public endpoint.
- [ ] Compare exact timestamp, OHLC, volume/trade fields, and funding values as canonical decimal strings.
- [ ] Record matched, mismatched, missing-from-remote, and missing-from-local counts plus complete field-level differences.

### Task 5: Coverage gate and reports

**Files:**
- Modify: `scripts/audit_binance_data_readiness.py`
- Create at runtime: `artifacts/data_readiness/data_readiness_report.json`
- Create at runtime: `artifacts/data_readiness/data_readiness_report.md`
- Create at runtime: `artifacts/data_readiness/endpoint_connectivity.json`
- Create at runtime: `artifacts/data_readiness/local_coverage.json`
- Create at runtime: `artifacts/data_readiness/freshness.json`
- Create at runtime: `artifacts/data_readiness/sample_reconciliation.json`
- Create at runtime: `artifacts/data_readiness/gap_report.json`
- Create at runtime when refreshed: `artifacts/data_readiness/refreshed_dataset_manifest.json`

**Interfaces:**
- Consumes: integrity, freshness, reconciliation, contract-rule, maintenance-evidence, and common-coverage results.
- Produces: one final readiness status and a `DIAGNOSTIC_ONLY` longest common interval when 66 months are unavailable.

- [ ] Require 36 training + 12 validation + 18 locked OOS months of common BTC/ETH trade/mark/funding/pre-roll coverage.
- [ ] Treat current-only contract rules as non-VERIFIED historical coverage and report maintenance-evidence absence explicitly.
- [ ] Apply status precedence: source unavailable, integrity failed, insufficient coverage, stale refresh required, ready.
- [ ] Include a minimal four-hour post-close REST refresh design only; do not implement a service.

### Task 6: Execute and verify the audit

**Files:**
- Runtime outputs only under `artifacts/data_readiness/`.

- [ ] Run the focused audit tests, all `tests/research_data`, Ruff, diff check, and compileall.
- [ ] Run the audit against the discovered local snapshot and live Binance public endpoints.
- [ ] Re-read every output artifact, verify exact UTC timestamps/counts/hashes and sample totals, and confirm source snapshot hashes are unchanged.
- [ ] Confirm no 2A/2B/2C files changed, no API key environment was read, and no account/order path was requested.
