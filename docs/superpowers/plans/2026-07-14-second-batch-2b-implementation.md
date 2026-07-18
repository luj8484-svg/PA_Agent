# Second-Batch 2B Execution Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` and complete the tasks in order with the stated RED/GREEN checkpoints.

**Goal:** Implement the frozen 2B deterministic execution-planning layer as pure Python value objects and pure functions, with complete evidence-chain validation and no trading, replay, account mutation, or external I/O capability.

**Architecture:** Immutable closed-schema domain objects live under `pa_agent/research_backtest/domain`; deterministic calculations and final factories live under `pa_agent/research_backtest/planning`. Every formal object serializes through the existing Canonical JSON rules and self-verifies its content hash and prefixed ID. Upstream market, contract, cost, funding, account, and completeness evidence is passed explicitly. Planning functions return a success object or a typed rejection/path-invalid result without mutating inputs. Test registration is collected from pytest case markers and compared bidirectionally with the five frozen test-ID sources.

**Tech Stack:** exact CPython 3.12.13 (`DETERMINISTIC_RESEARCH_RUNTIME_V1`), frozen `dataclass` value objects, `Decimal`, `pytest`, `hypothesis`, Ruff, Git.

## Global Constraints

- The authority order is frozen spec, acceptance matrix, illegal-state matrix, time-boundary matrix, golden-fixture plan, red-team matrix, then this plan.
- The formulas, comparison operators, half-open/closed time intervals, rejection priority, field sets, ID prefixes, and version strings in the frozen spec are copied exactly.
- Every task starts with a minimal failing test, records the failure, adds only the required production code, runs focused and regression tests, refactors while green, records the green command, and commits.
- Fixture manifests and independent `Decimal` reference implementations are written before the production formula they verify. A reference implementation must not import or call its production counterpart.
- Domain time comes only from market/experiment event fields. Wall-clock time, filesystem timestamps, and download timestamps never enter an object, hash, ID, comparison, or planning decision.
- All price, quantity, cost, margin, reserve, funding, balance, risk, and PnL values are `Decimal`; binary floats are rejected at boundaries.
- 2B contains no FillEvent, minute replay, account mutation, position mutation, funding settlement, protective-trigger evaluation, liquidation evaluation, ledger, PnL/performance reporting, GUI, LLM, HTTP, API key, authenticated exchange client, order creation, or live/paper order submission.
- The TDD evidence ledger is `docs/superpowers/evidence/2026-07-15-second-batch-2b-tdd.md` and receives one RED/GREEN/commit entry per task.

## Requirement Allocation

The acceptance matrix remains the row-level authority for the exact Requirement → Unit Test → Property Test → Fixture mapping. The following allocation is exhaustive over all 114 Requirement IDs and assigns each ID to exactly one implementation task.

| Task | Requirement IDs | Primary unit test IDs |
|---|---|---|
| 1 | `2B-ID-001`, `2B-ID-002`, `2B-ID-005`, `2B-ID-006`, `2B-ID-007`, `2B-ID-008`, `2B-SCOPE-001`, `2B-SCOPE-002`, `2B-SCOPE-003`, `2B-SCOPE-004`, `2B-SCOPE-005`, `2B-SCOPE-006`, `2B-TIME-007` | `UT-ID-001`, `UT-ID-002`, `UT-ID-005`, `UT-ID-006`, `UT-ID-007`, `UT-ID-008`; `UT-SCOPE-001`, `UT-SCOPE-002`, `UT-SCOPE-003`, `UT-SCOPE-004`, `UT-SCOPE-005`, `UT-SCOPE-006`; `UT-TIME-007` |
| 2 | `2B-LIFE-001`, `2B-LIFE-002`, `2B-SCHEMA-001`, `2B-SCHEMA-009`, `2B-SCHEMA-016`, `2B-SCHEMA-017`, `2B-TIME-001`, `2B-TIME-002`, `2B-TIME-008`, `2B-TIME-009`, `2B-TIME-013`, `2B-ID-003`, `2B-ID-004` | `UT-LIFE-001`, `UT-LIFE-002`; `UT-SCHEMA-001`, `UT-SCHEMA-009`, `UT-SCHEMA-016`, `UT-SCHEMA-017`; `UT-TIME-001`, `UT-TIME-002`, `UT-TIME-008`, `UT-TIME-009`, `UT-TIME-013`; `UT-ID-003`, `UT-ID-004` |
| 3 | `2B-SCHEMA-006`, `2B-SCHEMA-014`, `2B-TIME-005`, `2B-TIME-010`, `2B-TIME-012`, `2B-COST-004`, `2B-COST-006`, `2B-COST-007`, `2B-FUND-001`, `2B-FUND-002`, `2B-FUND-003`, `2B-FUND-004`, `2B-FUND-005`, `2B-FUND-006`, `2B-FUND-007`, `2B-FUND-008`, `2B-FUND-009`, `2B-RULE-001`, `2B-RULE-002`, `2B-RULE-003`, `2B-RULE-004`, `2B-RULE-005`, `2B-RULE-006`, `2B-RULE-007`, `2B-RULE-008`, `2B-RULE-009` | corresponding `UT-SCHEMA-*`, `UT-TIME-*`, `UT-COST-*`, `UT-FUND-*`, and `UT-RULE-*` IDs with the same suffixes |
| 4 | `2B-SCHEMA-015`, `2B-SCHEMA-020`, `2B-TIME-015`, `2B-RISK-006`, `2B-RISK-007`, `2B-RISK-010`, `2B-RISK-011`, `2B-RISK-012` | `UT-SCHEMA-015`, `UT-SCHEMA-020`; `UT-TIME-015`; `UT-RISK-006`, `UT-RISK-007`, `UT-RISK-010`, `UT-RISK-011`, `UT-RISK-012` |
| 5 | `2B-SCHEMA-005`, `2B-ID-005`, `2B-PORT-005`, plus rejection-priority coverage for every economic/data/path-invalid reason | `UT-SCHEMA-005`, `UT-ID-005`, `UT-PORT-005` and the relevant rejection cases declared in the master registry |
| 6 | `2B-SCHEMA-007`, `2B-SCHEMA-012`, `2B-SCHEMA-013`, `2B-GAP-001`, `2B-GAP-002`, `2B-GAP-003`, `2B-GAP-004`, `2B-COST-001`, `2B-COST-002`, `2B-COST-003`, `2B-COST-005`, `2B-RISK-001`, `2B-RISK-002`, `2B-RISK-003`, `2B-RISK-004`, `2B-RISK-009`, `2B-QTY-001`, `2B-QTY-002`, `2B-QTY-003`, `2B-QTY-004` | corresponding `UT-SCHEMA-*`, `UT-GAP-*`, `UT-COST-*`, `UT-RISK-*`, and `UT-QTY-*` IDs |
| 7 | `2B-LIFE-010`, `2B-SCHEMA-008`, `2B-SCHEMA-010`, `2B-SCHEMA-011`, `2B-SCHEMA-018`, `2B-SCHEMA-019`, `2B-TIME-011`, `2B-TIME-014`, `2B-RISK-005`, `2B-RISK-008`, `2B-PORT-001`, `2B-PORT-002`, `2B-PORT-003`, `2B-PORT-004`, `2B-PORT-005`, `2B-PORT-006`, `2B-PORT-007`, `2B-PORT-008`, `2B-PORT-009` | corresponding `UT-LIFE-*`, `UT-SCHEMA-*`, `UT-TIME-*`, `UT-RISK-*`, and `UT-PORT-*` IDs |
| 8 | `2B-LIFE-003`, `2B-LIFE-006`, `2B-LIFE-007`, `2B-LIFE-009`, `2B-LIFE-011`, `2B-SCHEMA-002`, `2B-TIME-004`, `2B-TIME-006`, `2B-RULE-004`, `2B-RULE-006` | `UT-LIFE-003`, `UT-LIFE-006`, `UT-LIFE-007`, `UT-LIFE-009`, `UT-LIFE-011`; `UT-SCHEMA-002`; `UT-TIME-004`, `UT-TIME-006`; `UT-RULE-004`, `UT-RULE-006` |
| 9 | `2B-LIFE-004`, `2B-LIFE-005`, `2B-LIFE-008`, `2B-SCHEMA-003`, `2B-SCHEMA-004`, `2B-TIME-003` | `UT-LIFE-004`, `UT-LIFE-005`, `UT-LIFE-008`; `UT-SCHEMA-003`, `UT-SCHEMA-004`; `UT-TIME-003` |
| 10 | All 114 Requirements as end-to-end traceability targets; supplemental illegal-state, time-boundary, golden, red-team IDs; all property families | the exact `MASTER_TEST_REGISTRY_V1` union: 114 unit, 109 property, and 212 supplemental IDs |

`2B-ID-005` and rejection behavior cross Task 1/5 because Task 1 supplies the canonical validator contract and Task 5 supplies domain rejection-priority behavior; the Requirement has one primary owner (Task 1) and explicit integration coverage in Task 5. `2B-RULE-004` has contract mode coverage in Task 3 and one primary factory owner in Task 8.

## Master Test Registry Contract

- `pa_agent/research_backtest/testing/registry.py` parses the five frozen sources and returns immutable `RegisteredTest` entries. It recognizes `UT-*` and `PT-*` test IDs and excludes `GF-*` fixture IDs.
- `scripts/validate_2b_test_registry.py` collects `tests/research_backtest/execution` with pytest, reads exactly one `test_id` marker and one non-empty `requirement_ids` marker from every collected case, and fails on empty collection, missing metadata, duplicate test ID, undocumented ID, missing documented ID, or unknown Requirement ID.
- Parameterized cases put markers on each `pytest.param`, so each collected node declares its own identity and Requirements.
- The final equality is `documented_master_test_id_set == implemented_test_id_set == 435 unique IDs` with `114 unit + 109 property + 212 supplemental`; 71 `GF-*` fixture IDs are not test IDs.
- Task 1 proves the validator against synthetic complete, empty, missing, orphan, duplicate, and fixture-ID inputs. Task 10 runs it against the real suite.

---

## Task 1: Versions, Canonical Identity, Master Registry, and Scope Guard

**Files:**

- Modify: `pa_agent/research_backtest/domain/canonical.py`
- Modify: `pa_agent/research_backtest/versions.py`
- Create: `pa_agent/research_backtest/domain/base.py`
- Create: `pa_agent/research_backtest/testing/__init__.py`
- Create: `pa_agent/research_backtest/testing/registry.py`
- Create: `scripts/validate_2b_test_registry.py`
- Create: `tests/research_backtest/execution/conftest.py`
- Create: `tests/research_backtest/execution/unit/test_registry_canonical_scope.py`
- Create: `tests/research_backtest/execution/acceptance/test_scope_guard.py`
- Create/modify: `docs/superpowers/evidence/2026-07-15-second-batch-2b-tdd.md`

**Interfaces:**

```python
def canonical_payload(value: object, *, excluded_fields: frozenset[str]) -> dict[str, object]
def content_hash(value: object, *, excluded_fields: frozenset[str]) -> str
def formal_id(prefix: str, content_hash_value: str) -> str
def verify_formal_identity(value: object, *, id_field: str, hash_field: str, prefix: str) -> None
def load_documented_master_registry(paths: FrozenDocumentPaths) -> tuple[RegisteredTest, ...]
def validate_registry(documented: tuple[RegisteredTest, ...], implemented: tuple[ImplementedTest, ...]) -> RegistryReport
```

**RED:** Add tests for closed canonical schemas, finite Decimal-only values, self-verifying hashes/IDs, five-source union, empty and asymmetric registry failures, duplicate IDs, non-empty Requirement bindings, and forbidden-capability AST/import scanning. Run the focused tests and record the expected import/behavior failures.

**GREEN:** Implement the smallest generic identity helpers, frozen 2B version constants, document parser, pytest collector/validator, and transitive scope scanner. Run focused tests, all existing 2A tests, first-batch tests, Ruff, and `git diff --check`.

**Commit:** `feat(research-2b): add canonical registry and scope foundations`

---

## Task 2: Entry Intent, Execution Time, and Open/Watermark Inputs

**Files:**

- Create: `pa_agent/research_backtest/domain/config.py`
- Create: `pa_agent/research_backtest/domain/market_inputs.py`
- Create: `pa_agent/research_backtest/domain/intents.py`
- Create: `pa_agent/research_backtest/planning/__init__.py`
- Create: `pa_agent/research_backtest/planning/time.py`
- Create: `pa_agent/research_backtest/planning/intents.py`
- Create: `tests/research_backtest/execution/unit/test_entry_intent_time_market.py`
- Create: `tests/research_backtest/execution/property/test_entry_intent_time_market_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def next_four_hour_anchor(decision_time_utc_ms: int) -> int
def entry_target_time(decision_time_utc_ms: int, config: ExecutionTimeConfig) -> int
def make_entry_intent(candidate: StrategyCandidate, config: ExecutionTimeConfig) -> EntryIntent | ExecutionRejection
def validate_target_open(snapshot: TargetMinuteOpenSnapshot, watermark: TargetEventWatermark, intent: EntryIntent) -> None
```

`TargetMinuteOpenSnapshot` identity contains only the frozen open-event fields and never a watermark or consumption time. `TargetEventWatermark` has independent `watermark_source_event_id` and remains constructible without a matching open snapshot. `EntryIntent` contains no future price, contract, cost, account, quantity, stop, or target-profit field.

**RED/GREEN tests:** exact 4H anchors; delay 0/1/2; `[target,target+60_000)` open matching; watermark at target and late; snapshot identity invariant under watermark changes; Candidate and EntryIntent history invariant under future data changes; NO_SETUP economic rejection; invalid Candidate data path; no wall clock.

**Commit:** `feat(research-2b): add entry intent and target-open evidence`

---

## Task 3: Contract, Cost, Funding Schedule, and Funding Risk

**Files:**

- Create: `pa_agent/research_backtest/domain/contracts.py`
- Create: `pa_agent/research_backtest/domain/costs.py`
- Create: `pa_agent/research_backtest/domain/funding.py`
- Create: `pa_agent/research_backtest/planning/funding.py`
- Create: `tests/research_backtest/execution/fixtures/reference_funding.py`
- Create: `tests/research_backtest/execution/unit/test_contract_cost_funding.py`
- Create: `tests/research_backtest/execution/property/test_contract_cost_funding_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def resolve_contract_coverage(snapshot: ContractRuleArchiveSnapshot, target_time_utc_ms: int, stage: ResearchStage) -> ContractRuleCoverage | ExecutionRejection
def funding_windows_between(schedule: FundingScheduleSnapshot, entry_time_utc_ms: int, exit_time_utc_ms: int) -> tuple[FundingWindow, ...]
def effective_adverse_rate(config: FundingRiskConfig) -> Decimal
def funding_reserve_per_unit(window_count: int, price_basis: Decimal, config: FundingRiskConfig) -> Decimal
```

**RED/GREEN tests:** VERIFIED/APPROXIMATED/UNAVAILABLE tagged unions; `[valid_from,valid_to)`; PRIOR_ONLY evidence timing; HINDSIGHT diagnostics excluded from Paper/Live and primary OOS; review enum; positive tick/step/minimums; cost/risk config hash closure; funding `(entry,max_exit]`; exact endpoint inclusion; irregular schedules; full coverage; seven-settlement 48h edge; `0.0001` baseline watermark; stress multipliers 1/1.5/2; future evidence rejection.

**Commit:** `feat(research-2b): add contract cost and funding evidence`

---

## Task 4: Account Snapshot and Evidence Bundle

**Files:**

- Create: `pa_agent/research_backtest/domain/accounts.py`
- Create: `tests/research_backtest/execution/fixtures/reference_account.py`
- Create: `tests/research_backtest/execution/unit/test_account_evidence.py`
- Create: `tests/research_backtest/execution/property/test_account_evidence_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def replay_account_evidence(bundle: AccountPlanningEvidenceBundle) -> AccountEvidenceAggregates
def make_account_planning_snapshot(bundle: AccountPlanningEvidenceBundle, eligible_time_utc_ms: int) -> AccountPlanningSnapshot | ExecutionRejection
def validate_account_snapshot(snapshot: AccountPlanningSnapshot, bundle: AccountPlanningEvidenceBundle) -> None
```

The evidence bundle stores/references the complete immutable ledger source, valuation snapshots, position records, open-risk records, pending-plan records, experiment state, set IDs/hashes, and aggregates. `current_equity = wallet_balance + unrealized_pnl`; valuation basis is the frozen mark-price open at eligible time. Available balance, existing risk, pending risk/reserve, position symbols, collection hashes, event time, and planning phase are replayed before acceptance. Naked hashes yield `REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE` / path invalid.

**RED/GREEN tests:** empty/one/many record sets; negative unrealized PnL; stale/future valuation; aggregate-only mutation; collection/hash mutation; pending reserve equal to and above available; missing open-risk evidence; immutable replay; no account mutation.

**Commit:** `feat(research-2b): add replayable account planning evidence`

---

## Task 5: Rejection Subjects, Matrix, and Priority

**Files:**

- Create: `pa_agent/research_backtest/domain/rejections.py`
- Create: `pa_agent/research_backtest/planning/rejections.py`
- Create: `tests/research_backtest/execution/unit/test_rejection_matrix.py`
- Create: `tests/research_backtest/execution/property/test_rejection_priority_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def rejection_subject_for(value: object) -> RejectionSubjectRef
def choose_rejection(facts: tuple[RejectionFact, ...]) -> ExecutionRejection
def classify_failure(reason: RejectionReason) -> FailureClass
```

**RED/GREEN tests:** closed tagged subject variants with exact cardinality; stable portfolio-batch subject across input permutations; the complete frozen rejection enum and priority table; validator-order invariance; market conclusions kept separate from execution rejection; economic rejection versus `DATA_INVALID`, `EXECUTION_PATH_INVALID`, and `EXPERIMENT_INVALID`; no empty/wrong/stale subject identity.

**Commit:** `feat(research-2b): add typed rejection subjects and priority`

---

## Task 6: Price, Gap, Reserve, and Position Sizing

**Files:**

- Create: `pa_agent/research_backtest/domain/sizing.py`
- Create: `pa_agent/research_backtest/planning/prices.py`
- Create: `pa_agent/research_backtest/planning/costs.py`
- Create: `pa_agent/research_backtest/planning/sizing.py`
- Create: `tests/research_backtest/execution/fixtures/reference_decimal_formulas.py`
- Create: `tests/research_backtest/execution/unit/test_price_gap_sizing.py`
- Create: `tests/research_backtest/execution/property/test_price_gap_sizing_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def adverse_gap(side: Side, candidate_close: Decimal, target_open: Decimal) -> Decimal
def entry_fill_price(side: Side, target_open: Decimal, slippage_rate: Decimal, tick_size: Decimal) -> Decimal
def protective_price_geometry(side: Side, entry_fill: Decimal, atr: Decimal, config: RiskConfig, tick_size: Decimal) -> PriceGeometry | ExecutionRejection
def exit_fee_reserve(quantity: Decimal, geometry: PriceGeometry, cost: CostModelSnapshot) -> Decimal
def position_sizing(inputs: SizingInputs) -> PositionSizingResult | ExecutionRejection
```

The independent fixture reference is implemented first using only `Decimal` primitives. Gap is measured against unslipped `P0`; equality with `0.5 * ATR` passes; entry and expected exit prices apply slippage exactly once; tick rounding is directional; geometry is strict. Unit risk, 0.5% budget, raw quantity, step-floor quantity, planned-risk recomputation, minimum checks, fee envelope, and funding envelope use the frozen formulas without pre-rounding.

**RED/GREEN tests:** LONG/SHORT monotonic gaps; exact gap threshold; cost independence; zero/stressed slippage; directional tick edges; no double slippage; reserve max envelope; geometry collision; raw quantity zero/repeating Decimal; step boundaries; minQty/minNotional equality; quantity-zero precedence; final risk invariant.

**Commit:** `feat(research-2b): add deterministic price and sizing formulas`

---

## Task 7: Batch Completeness, Planning Batch, and Portfolio Scaling

**Files:**

- Create: `pa_agent/research_backtest/domain/batches.py`
- Create: `pa_agent/research_backtest/domain/scaling.py`
- Create: `pa_agent/research_backtest/planning/portfolio.py`
- Create: `tests/research_backtest/execution/fixtures/reference_portfolio.py`
- Create: `tests/research_backtest/execution/unit/test_batch_scaling.py`
- Create: `tests/research_backtest/execution/property/test_batch_scaling_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def make_completeness_snapshot(expected_intents: tuple[EntryIntent, ...], resolutions: tuple[ResolutionRef, ...], event: CompletenessEvent) -> PortfolioBatchCompletenessSnapshot
def make_planning_batch(completeness: PortfolioBatchCompletenessSnapshot, sizing_results: tuple[PositionSizingResult, ...]) -> PortfolioPlanningBatch
def scale_portfolio(batch: PortfolioPlanningBatch, account: AccountPlanningSnapshot) -> PortfolioScalingResult | ExecutionRejection
```

Each expected EntryIntent has exactly one resolution of `SIZING_RESULT`, `ECONOMIC_REJECTION`, `EXECUTION_PATH_INVALID`, or `EXPERIMENT_INVALID`; missing, duplicate, extra, cross-symbol, or pre-eligible resolutions fail. Only successful sizing results enter scaling, while all failures remain in completeness evidence. Scaling binds exactly one batch and requires ordered input result IDs equal to the batch successful projection. Scale is `min(1, risk_limit_scale, cash_limit_scale)`, applies once to all accepted inputs, floors by step, performs no redistribution, and rejects base risk at/above 1% without synthesizing zero quantities. Accepted items have no opaque input hash.

**RED/GREEN tests:** BTC/ETH simultaneous completeness; four resolution kinds; partial/duplicate/extra/cross-batch cases; order permutations; risk/cash/tie limiters; base-risk exact threshold; minimum rejection after scale; no redistribution; nested item identity; accepted-item self-proof; Batch → ScalingResult → item chain.

**Commit:** `feat(research-2b): add complete batch portfolio scaling`

---

## Task 8: Final Entry Execution Plan Factory

**Files:**

- Create: `pa_agent/research_backtest/domain/plans.py`
- Create: `pa_agent/research_backtest/planning/factory.py`
- Create: `tests/research_backtest/execution/unit/test_entry_plan_factory.py`
- Create: `tests/research_backtest/execution/property/test_entry_plan_factory_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def build_entry_execution_plan(inputs: EntryPlanningInputs) -> EntryExecutionPlan | ExecutionRejection
def validate_entry_evidence_chain(plan: EntryExecutionPlan, inputs: EntryPlanningInputs) -> None
```

The factory validates Candidate/Intent, target open and independent watermark, contract/cost/funding inputs, account evidence, completeness, batch, scaling result, accepted item, experiment state, split bounds, and every ID/hash link before constructing the plan. Plan quantity comes only from `AcceptedScalingItem`; target-open input hash excludes watermark; contract version changes alter plan identity; future bars, split labels, wall clock, and validation order do not. `HALTED` blocks new entry with `EXPERIMENT_HALTED`; absent evidence invalidates the execution path. The factory is pure and emits no Fill or mutation.

**RED/GREEN tests:** full one/two-symbol chain; stale/wrong link at each boundary; target-open absent after watermark; contract unavailable/expired; account evidence unavailable; split bounds; future-data invariance; delay sensitivity; rule-version sensitivity; deterministic repeated calls; intraminute halt gate; no forbidden plan fields.

**Commit:** `feat(research-2b): add final entry planning factory`

---

## Task 9: Scheduled Exit Intent and Exit Plan

**Files:**

- Modify: `pa_agent/research_backtest/domain/intents.py`
- Modify: `pa_agent/research_backtest/domain/plans.py`
- Create: `pa_agent/research_backtest/planning/exits.py`
- Modify: `pa_agent/research_backtest/planning/factory.py`
- Create: `tests/research_backtest/execution/unit/test_exit_planning.py`
- Create: `tests/research_backtest/execution/property/test_exit_planning_properties.py`
- Modify: TDD evidence ledger

**Interfaces:**

```python
def make_scheduled_exit_intent(condition: ScheduledExitCondition, position: PositionPlanningSnapshot, config: ExecutionTimeConfig) -> ExitIntent
def build_exit_execution_plan(inputs: ExitPlanningInputs) -> ExitExecutionPlan | ExecutionRejection
```

Only `TIME_EXIT`, `TREND_EXIT`, `HALT_EXIT`, and `END_OF_DATA_EXIT` are accepted. STOP, TP, and liquidation remain outside 2B. Exit target is strictly after condition time. The plan waits for the future target-open snapshot, permits HALT exit while the experiment is halted, rejects changed position identity, and contains no entry risk/margin/reserve or protective-trigger fields.

**RED/GREEN tests:** each scheduled reason; rejected protective reason; strict future target; condition exactly on minute boundary; missing/late snapshot; independent watermark; unchanged/changed position; HALTED exit allowed; pure repeated construction.

**Commit:** `feat(research-2b): add scheduled exit planning`

---

## Task 10: Golden Fixtures, Properties, Master Registry, and Integration Acceptance

**Files:**

- Create: `tests/research_backtest/execution/fixtures/second_batch_2b_manifest_v1.json`
- Create: `tests/research_backtest/execution/fixtures/second_batch_2b_golden_v1.json`
- Create: `tests/research_backtest/execution/golden/test_golden_fixtures.py`
- Create: `tests/research_backtest/execution/integration/test_entry_lifecycle.py`
- Create: `tests/research_backtest/execution/integration/test_exit_lifecycle.py`
- Create: `tests/research_backtest/execution/integration/test_evidence_chain.py`
- Create: `tests/research_backtest/execution/supplemental/test_illegal_state_matrix.py`
- Create: `tests/research_backtest/execution/supplemental/test_time_boundary_matrix.py`
- Create: `tests/research_backtest/execution/supplemental/test_golden_fixture_matrix.py`
- Create: `tests/research_backtest/execution/supplemental/test_red_team_matrix.py`
- Create: `tests/research_backtest/execution/property/test_master_properties.py`
- Modify: `tests/research_backtest/execution/conftest.py`
- Modify: TDD evidence ledger

**Interfaces and collection:** Every collected 2B pytest case has one `test_id` and one non-empty `requirement_ids` marker. Data-driven matrix cases are real parametrized pytest cases with per-parameter markers and a behavior-specific scenario adapter. The 71 fixture identities are verified by their manifest but excluded from the test-ID set.

**RED:** Run the real registry validator before filling the remaining matrix declarations; record the exact documented-but-missing IDs. Add golden/integration/property cases and observe a formula/evidence-chain failure before production correction if any behavior is incomplete.

**GREEN:** Achieve the exact 435-ID bidirectional equality. Run all 114 unit/acceptance cases, 109 property cases, 212 supplemental cases, fixture validation, entry/exit integration, scope/safety scanners, and RT-1 through RT-53. Run first-batch 125-case and 2A 73-case regressions, then full `tests/research_data` and `tests/research_backtest` suites.

**Commit:** `test(research-2b): complete frozen acceptance and red-team matrix`

---

## Final Verification and Draft PR

Run and retain complete output for:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution -v
.\.venv\Scripts\python.exe scripts/validate_2b_test_registry.py
.\.venv\Scripts\python.exe -m pytest tests/research_data -v
.\.venv\Scripts\python.exe -m pytest tests/research_backtest -v
.\.venv\Scripts\ruff.exe check pa_agent/research_backtest tests/research_backtest scripts/validate_2b_test_registry.py
.\.venv\Scripts\ruff.exe format --check pa_agent/research_backtest tests/research_backtest scripts/validate_2b_test_registry.py
.\.venv\Scripts\python.exe -m compileall pa_agent/research_backtest
git diff --check fork/main...HEAD
```

Also run the 2B scope guard, public-security guard, production capability scan, wall-clock scan, float scan, mutation/replay/Fill/ledger/PnL scan, API/auth/order scan, and the RT-1–RT-53 self-red-team suite. Verify the branch contains no 2C implementation and no GUI, LLM, HTTP, API key, authenticated client, or trading interface code.

Push `feature/second-batch-2b-execution-planning`, create a Draft PR against the user fork `main`, attach the plan/traceability/registry/test evidence, and stop without merging or starting 2C.
