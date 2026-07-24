# Binance Historical Data Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill official Binance USD-M BTCUSDT/ETHUSDT market history, audit integrity, and produce a natural-month experiment split candidate without running 2D.

**Architecture:** Discover monthly objects through the official `data.binance.vision` S3 listing, estimate resources before download, and store immutable ZIP/checksum shards outside Git. Canonicalize each monthly shard independently, merge it with a public-REST closed-bar tail, validate every required stream, and emit deterministic manifests and reports. Existing 2A/2B/2C code remains untouched.

**Tech Stack:** CPython 3.12.13, standard-library urllib/zipfile/csv/hashlib/json, existing `pa_agent.research_data` canonicalization and public REST client, pytest, Ruff.

## Global Constraints

- Official sources only: `https://data.binance.vision` and `https://fapi.binance.com` six allowlisted public GET endpoints.
- No API key, account endpoint, order endpoint, synthetic fill, WebSocket, GUI, LLM, 2D execution, or changes to 2A/2B/2C.
- Formal split uses 250 complete UTC daily pre-roll bars, then 36/12/18 complete UTC calendar months in chronological order.
- Raw and canonical bulk files are immutable, resumable, and Git-ignored.
- Resource gate requires free bytes greater than or equal to estimated final bytes multiplied by 1.5 before any archive download.
- Critical trade/mark/funding gaps fail closed; no missing bar is fabricated.

---

### Task 1: Archive inventory and natural-month split semantics

**Files:**
- Create: `pa_agent/research_data/historical_archive.py`
- Test: `tests/research_data/test_historical_archive.py`

**Interfaces:**
- Produces `list_archive_objects()`, `month_range()`, `build_experiment_split_candidate()`, and exact UTC boundary records.

- [ ] Write failing tests for official-host enforcement, XML listing parsing, earliest/latest month discovery, leap-year month boundaries, 250-day pre-roll, and 36/12/18 chronological natural-month splits.
- [ ] Run `pytest tests/research_data/test_historical_archive.py -v` and confirm missing imports fail.
- [ ] Implement only the tested inventory and split functions.
- [ ] Re-run the focused tests and Ruff.

### Task 2: Resource estimate and disk gate

**Files:**
- Modify: `pa_agent/research_data/historical_archive.py`
- Test: `tests/research_data/test_historical_archive.py`

**Interfaces:**
- Produces `estimate_resources(objects, free_bytes)` with compressed, extracted, canonical, manifest, request, runtime, safety-required, and capacity status fields.

- [ ] Write failing tests that reject a disk budget below `estimated_final_bytes * 1.5` before downloader invocation.
- [ ] Run the focused failing test.
- [ ] Implement deterministic integer estimates using official object sizes and conservative measured expansion/canonical ratios.
- [ ] Re-run focused tests and verify no partial output is created on rejection.

### Task 3: Immutable resumable archive acquisition and monthly canonicalization

**Files:**
- Modify: `pa_agent/research_data/historical_archive.py`
- Create: `scripts/backfill_binance_historical.py`
- Modify: `.gitignore`
- Test: `tests/research_data/test_historical_archive.py`

**Interfaces:**
- Produces per-object raw checksum evidence, per-month canonical JSONL/hash, archive manifest, and an atomic resume state.

- [ ] Write failing fixture-ZIP tests for checksum enforcement, header/no-header CSV, idempotent resume, immutable raw conflict rejection, OHLC geometry, finite Decimal values, ordering, duplicates, and conflicting duplicates.
- [ ] Run focused tests and observe the intended failures.
- [ ] Implement streaming download to `.part`, SHA-256 verification against official `.CHECKSUM`, atomic rename, and independent monthly canonicalization.
- [ ] Add `/artifacts/historical_data_readiness/data/` to `.gitignore` and verify `git check-ignore` for raw and canonical examples.
- [ ] Re-run tests and Ruff.

### Task 4: REST tail, full integrity, and native cross-validation

**Files:**
- Modify: `scripts/backfill_binance_historical.py`
- Modify: `pa_agent/research_data/historical_archive.py`
- Test: `tests/research_data/test_historical_archive.py`

**Interfaces:**
- Consumes archive monthly manifests and existing `BinancePublicClient`; produces REST-tail manifest and per-stream gap/cross-validation reports.

- [ ] Write failing tests for closed-bar REST tail boundaries, critical-gap failure, funding schedule evidence, and exact native 4H/1D comparison against aggregated 1m bars.
- [ ] Run focused tests and confirm failures.
- [ ] Implement bounded public GET tail acquisition and complete timestamp/hash/integrity validation without synthetic filling.
- [ ] Re-run focused tests and existing `tests/research_data`.

### Task 5: Annual online reconciliation and approximation disclosures

**Files:**
- Modify: `scripts/backfill_binance_historical.py`
- Test: `tests/research_data/test_historical_archive.py`

**Interfaces:**
- Produces annual fixed-seed samples and static approximation policy/materiality readiness records without executing trades.

- [ ] Write failing tests for annual sample quotas and required earliest/training/validation/OOS/latest coverage.
- [ ] Implement deterministic SHA-256 sampling and exact Decimal/time reconciliation via public REST.
- [ ] Emit `APPROXIMATED_CURRENT_RULES_V1` and `APPROXIMATED_MAINTENANCE_MODEL_V1`; mark execution-level sensitivity/materiality as pending 2D because no plans/trades are generated in this task.
- [ ] Re-run focused tests.

### Task 6: Execute backfill and final audit

**Files:**
- Generate: `artifacts/historical_data_readiness/*.json`
- Generate: `artifacts/historical_data_readiness/final_data_readiness_report.md`

**Interfaces:**
- Produces all twelve required reports and one of the six allowed final statuses.

- [ ] Run discovery and resource estimation first; stop on source or disk failure.
- [ ] If the gate passes, download/checksum/canonicalize official monthly shards and add the public REST tail.
- [ ] Run full integrity, gap, cross-validation, annual reconciliation, and natural-month split generation.
- [ ] Assert all required artifacts exist, bulk data is ignored, no 2A/2B/2C path changed, and no 2D/API-key/trading capability ran.
- [ ] Run `pytest tests/research_data -q`, Ruff check/format, compileall, and `git diff --check`.
