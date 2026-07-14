# Second Batch 2A Indicator and Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement only the deterministic 2A indicator, pre-roll, visible-input identity, StrategyCandidate, ValidationFailure, Golden Fixture, and static scope-guard boundary.

**Architecture:** A new isolated `pa_agent.research_backtest` package consumes immutable first-batch `Kline` records but performs no I/O. Small pure-function modules calculate scalar float indicators, Decimal boundaries, segment/pre-roll selection, visible-input hashes, and immutable domain results. No execution, risk, position, fee, event, ledger, report, HTTP, GUI, or LLM module is permitted.

**Tech Stack:** CPython 3.12.13, Python standard library dataclasses/Decimal/hashlib/json, pytest, Hypothesis, Ruff.

## Global Constraints

- Strategy version is `BTC_ETH_PA_STRATEGY_V1_1`.
- Schema versions are `STRATEGY_CANDIDATE_SCHEMA_V1` and `VALIDATION_FAILURE_SCHEMA_V1`.
- Indicator configuration is `INDICATOR_CONFIG_V1`, locked to CPython 3.12.13 and fixed-order scalar Python float recurrence.
- Initial pre-roll is exactly the final 250 continuous closed 1D bars and 100 continuous closed 4H bars before training start.
- Training start follows rule A: it is aligned to both UTC 1D and 4H boundaries; pre-roll never emits Candidate, and the first eligible decision bar opens at or after training start.
- Validation priority is `PRE_ROLL_INSUFFICIENT > DATA_SEGMENT_NOT_CONTINUOUS > INDICATOR_WARMING_UP`.
- Candidate market view is only `LONG | SHORT | NO_SETUP`.
- Candidate identity excludes execution intent/delay and full-interval dataset/acquisition hashes.
- `decision_visible_input_hash` includes only bars and validation/version state visible at the decision time.
- No wall-clock value, I/O, network client, account/contract rule, order, execution, position, fee, event, ledger, report, GUI, or LLM dependency.

---

### Task 1: Version, Canonical, and Numeric Boundary

**Files:**
- Create: `pa_agent/research_backtest/__init__.py`
- Create: `pa_agent/research_backtest/versions.py`
- Create: `pa_agent/research_backtest/domain/canonical.py`
- Create: `pa_agent/research_backtest/indicators/numeric.py`
- Test: `tests/research_backtest/unit/test_versions_numeric_canonical.py`

**Interfaces:**
- Produces: `assert_runtime_lock()`, `canonical_dumps(value)`, `canonical_sha256(value)`, `float64_to_decimal_15sig(value)`.
- Consumes: no project business modules.

- [ ] Write failing tests that import the four interfaces, assert formal version constants, reject binary floats in Canonical data, normalize Decimal negative zero, and cover zero/subnormal/large finite/non-finite numeric inputs.
- [ ] Run `python -m pytest tests/research_backtest/unit/test_versions_numeric_canonical.py -v`; expect import failure because the 2A package does not exist.
- [ ] Add the minimum version, Canonical, runtime-lock, and numeric implementations. The decimal exponent must come from `Decimal.from_float(value).adjusted()` and use `ROUND_HALF_EVEN`.
- [ ] Re-run the test file; expect all tests to pass.
- [ ] Run Ruff on the created files and commit as `feat(research-2a): add deterministic numeric boundary`.

### Task 2: EMA, ATR, Donchian, and Golden Fixtures

**Files:**
- Create: `pa_agent/research_backtest/indicators/ema.py`
- Create: `pa_agent/research_backtest/indicators/atr.py`
- Create: `pa_agent/research_backtest/indicators/donchian.py`
- Create: `tests/research_backtest/fixtures/indicator_golden_v1.json`
- Test: `tests/research_backtest/unit/test_indicators.py`
- Test: `tests/research_backtest/property/test_indicator_determinism.py`

**Interfaces:**
- Produces: `ema(values, period)`, `wilder_atr(highs, lows, closes, period)`, and `previous_donchian(highs, lows, index, lookback)`.
- Consumes: Task 1 runtime and Decimal boundary functions.

- [ ] Write failing Golden Fixture tests for EMA seed/min-periods, Wilder ATR seed/recurrence, and exact `high[t-20:t]`/`low[t-20:t]` Donchian boundaries.
- [ ] Run the indicator unit tests; expect missing-module failures.
- [ ] Implement fixed-order scalar float EMA/ATR and Decimal Donchian with finite/positive input validation.
- [ ] Re-run unit tests; expect pass.
- [ ] Add property tests comparing production functions to independent scalar reference loops and asserting 0 ULP under the runtime lock.
- [ ] Run unit and property tests, Ruff, then commit as `feat(research-2a): add frozen indicator engine`.

### Task 3: Exact Pre-roll, Segment Reset, and Visible Input Hash

**Files:**
- Create: `pa_agent/research_backtest/domain/validation.py`
- Create: `pa_agent/research_backtest/strategy/pre_roll.py`
- Create: `pa_agent/research_backtest/strategy/visible_input.py`
- Test: `tests/research_backtest/unit/test_pre_roll_segments.py`
- Test: `tests/research_backtest/unit/test_visible_input_hash.py`

**Interfaces:**
- Produces: frozen `VisibleValidationState`, `select_exact_pre_roll(...)`, `active_segment(...)`, `highest_priority_failure(...)`, and `decision_visible_input_hash(...)`.
- Consumes: immutable `pa_agent.research_data.models.Kline`, Task 1 Canonical hashing, and formal versions.

- [ ] Write failing tests for exactly 250D/100×4H selection, 249/99 failure, continuity, no split reset, gap-first failure, post-gap warm-up, and frozen failure priority.
- [ ] Run pre-roll tests; expect missing-module failures.
- [ ] Implement sorting, duplicate rejection, closed-bar checks, exact pre-roll selection, contiguous segment reset, and priority selection as pure functions.
- [ ] Re-run pre-roll tests; expect pass.
- [ ] Write failing hash tests proving input-order independence and proving that future bars, acquisition metadata, and execution-delay changes cannot affect a past visible-input hash.
- [ ] Implement visible payload serialization using only the active visible 1D/4H segments, validation state, and indicator versions; re-run tests and commit as `feat(research-2a): freeze decision-visible inputs`.

### Task 4: Candidate, ValidationFailure, Strategy Rules, and Scope Guards

**Files:**
- Create: `pa_agent/research_backtest/domain/enums.py`
- Create: `pa_agent/research_backtest/domain/candidates.py`
- Create: `pa_agent/research_backtest/domain/failures.py`
- Create: `pa_agent/research_backtest/strategy/btc_eth_pa_v1.py`
- Create: `pa_agent/research_backtest/strategy/candidate_factory.py`
- Create: `tests/research_backtest/fixtures/strategy_golden_v1.json`
- Test: `tests/research_backtest/unit/test_strategy_candidate.py`
- Test: `tests/research_backtest/property/test_candidate_determinism.py`
- Test: `tests/research_backtest/acceptance/test_scope_guard.py`

**Interfaces:**
- Produces: frozen `StrategyCandidate`, frozen `ValidationFailure`, `classify_market(...)`, and `build_candidate(...) -> StrategyCandidate | ValidationFailure`.
- Consumes: Tasks 1–3 only plus first-batch immutable Kline records.

- [ ] Write failing truth-table tests for LONG/SHORT/NO_SETUP and strict Donchian equality boundaries.
- [ ] Run strategy tests; expect missing-module failures.
- [ ] Implement enums and the pure market classifier; re-run truth-table tests.
- [ ] Write failing Schema/ID tests that prohibit execution/contract/position fields, verify frozen dataclasses, and require IDs to hash all non-ID Canonical fields.
- [ ] Implement Candidate and ValidationFailure constructors and `build_candidate`, including pre-roll/gap/warm-up priority and selected closed daily bar visibility.
- [ ] Add future-data, wall-clock, split-label, execution-delay, input-order, byte-for-byte Golden Fixture, and repeated-run property tests.
- [ ] Add an AST/text scope guard that rejects forbidden packages, module names, HTTP/network imports, API credentials, account/order paths, and `create_order`.
- [ ] Run all 2A tests and Ruff; commit as `feat(research-2a): add deterministic strategy candidate`.

### Task 5: Acceptance and PR Handoff

**Files:**
- Modify only if a discovered defect requires a test-first fix within the Task 1–4 files.

**Interfaces:**
- Consumes: all 2A outputs.
- Produces: verified branch and Draft PR; no 2B artifacts.

**PR #1 review remediation:**

- [x] Add `DECISION_BEFORE_TRAINING_START` and aligned training-start boundary tests.
- [x] Select the exact pre-roll window before rejecting duplicates; validate only the newest active suffix after a gap.
- [x] Populate constructible failure visible hashes plus required/observed/gap evidence and deterministic IDs.
- [x] Add `STRATEGY_CANDIDATE_GOLDEN_V1`, independent ATR zero-ULP, Donchian, and Candidate reference checks.
- [x] Enforce Candidate direction/reason/trend, positive finite price, Donchian ordering, event-time ordering, and hash formats.

- [ ] Run `python -m pytest tests/research_backtest -v`.
- [ ] Run `python -m pytest tests/research_data -v` and the dedicated first-batch security/scope tests.
- [ ] Run Ruff, `git diff --check`, `python -m compileall pa_agent/research_backtest`, scope scans, deterministic repeated runs, and `main` versus feature first-batch regression comparison.
- [ ] Inspect the final directory tree and diff to prove no 2B module or symbol exists.
- [ ] Push `feature/second-batch-2a-indicator-candidate`, create a Draft PR to the fork `main`, report complete command output and known limits, then stop.
