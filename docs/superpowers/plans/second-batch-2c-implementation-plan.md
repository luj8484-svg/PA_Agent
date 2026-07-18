# Second-Batch 2C Minimal Event Engine Implementation Plan

状态：`APPROVED_FOR_TDD_IMPLEMENTATION`

**Goal:** Build a deterministic UTC one-minute BTC/ETH historical simulation that creates 2B Plans from target-minute state, consumes successful Plans, and emits immutable execution/account/path facts.

**Architecture:** A single-threaded pure reducer executes `MINUTE_EVENT_ORDER_V2`. Complete runs consume Candidates and evidence, not future-state Plan files. At each target minute the engine constructs one shared account/evidence bundle and invokes the existing 2B Sizing→Batch→Scaling→Plan pure-function chain exactly once for all due BTC/ETH Intents. Economic state changes only through Ledger reduction. BASELINE and CONSERVATIVE exist from simulation start and remain exactly two stable identities.

**Tech Stack:** exact CPython 3.12.13 (`DETERMINISTIC_RESEARCH_RUNTIME_V1`), frozen slotted dataclasses, Decimal, pytest, Hypothesis, existing 2A/2B Canonical and planning utilities.

## Global constraints

- Scope is exactly 60 Requirements, 24 Timeline Registry entries, 6 full Canonical Goldens, 24 Property Registry IDs mapped to 9 actual Property functions, and 34 red-team scenarios in the frozen package.
- Final closeout order is runtime guard, disposition execution, mark-based valuation, atomic Entry batch, run/output identity, production evidence bridge, then Registry/Golden verification. No stage may emit partial economic output after a fail-closed result.
- No GUI, LLM, API Key, authentication, HTTP/socket client, `create_order`, paper/live automation, 2D performance analytics, walk-forward, OOS, or parameter grid.
- 2C calls but never copies or alters 2B planning formulas. Candidate/Intent/Plan Canonical bytes are immutable.
- Complete run input contains Candidates/evidence/SimulationConfig; direct Plan injection exists only in isolated fixtures marked `LOCAL_PLAN_FIXTURE_ONLY`.
- Only closed UTC 1m data; trade drives fills/stop/TP, mark drives estimated liquidation/equity, historical funding drives settlement.
- All economic values use Decimal. Every task starts with an independent reference or Golden, then RED test, then minimal production code, then GREEN verification.
- No task may create a Fill before the Ledger reducer required to apply it exists.

## Planned file map

- `simulation/domain.py`: SimulationConfig, Events, Fill, Position, Ledger, Account, Equity, Trade, Path.
- `simulation/versions.py`: closed 2C schema/order/model versions.
- `simulation/identity.py`: config/run/output Canonical identity.
- `simulation/inputs.py`: closed-minute slices, Candidate scheduling, contextual gaps.
- `simulation/planning.py`: adapters that construct current evidence and call existing 2B planners.
- `simulation/ledger.py`: only economic-state reducer, locks/reserves/invariants.
- `simulation/funding.py`: historical funding and reserve slices.
- `simulation/liquidation.py`: maintenance evidence and estimated liquidation reference.
- `simulation/positions.py`: immutable isolated-position lifecycle.
- `simulation/fills.py`: Entry/Scheduled/protective fill facts.
- `simulation/triggers.py`: open-gap and intraminute trigger discovery.
- `simulation/ambiguity.py`: bounded policy selection.
- `simulation/halt.py`: open/intraminute HALT exposure policy.
- `simulation/engine.py`: `MINUTE_EVENT_ORDER_V2` orchestration.
- `simulation/output.py`: Canonical JSONL projections and manifest.
- `simulation/scope_guard.py`: forbidden capability scan.
- `tests/research_backtest/simulation/`: unit/property/Timeline/registry tests.

## Task 1 — Domain, versions, SimulationConfig, Canonical, scope guard

Interfaces:

- Immutable closed schemas for `SimulationConfig`, input/evidence refs, Event, Fill, Position, Ledger, AccountState, EquityPoint, TradeRecord, StateSnapshot, PathResult.
- `make_simulation_config(...)`, `initial_engine_state(config)`, `simulation_run_id(inputs, config)`.

- [ ] Write independent Canonical examples and RED tests for closed schemas, float rejection, UTC 1m alignment, initial balances/locks, identity tamper, wall-clock independence and forbidden imports.
- [ ] Implement versions and domain objects using existing 2B Canonical utilities.
- [ ] Prove acquisition metadata and pre-generated Plan files cannot enter run identity.
- [ ] Run focused tests and existing 2A/2B tests; commit.

## Task 2 — Input slice, Candidate/Intent scheduling, fail-closed gate

Interfaces:

- `build_minute_slice(...) -> MinuteInputSlice`
- `schedule_candidate(candidate, execution_config) -> EntryIntent`
- `validate_minute_inputs(state, slice) -> ValidatedMinuteInputs | PathInvalidEvent`

- [ ] Create TL-10..13 and independent contextual-gap classifier before production code.
- [ ] RED-test closed bars, UTC alignment, future visibility, trade/mark/funding contextual gaps, index audit-only, terminal INVALID without fake Equity.
- [ ] Implement immutable scheduling and gate with no filesystem/network access.
- [ ] Verify Candidate bytes/ID unchanged by future data and execution delay.

## Task 3 — Ledger, AccountState, locks, reserve and invariants

Interfaces:

- `reduce_ledger(previous, entries) -> AccountState`
- `validate_account_state(state) -> None | PathInvalidEvent`

- [ ] Build an independent Decimal double-entry/conservation reference.
- [ ] RED-test every Ledger kind, wallet/equity/available identities, fixed isolated margin, lock/release, replay idempotency and negative-state fail closed.
- [ ] Implement the sole account mutator before any production Fill is created.
- [ ] Property-test arbitrary valid event sequences and forbidden double deductions.

## Task 4 — Funding and maintenance/liquidation references

Interfaces:

- `settle_funding(position, record) -> FundingSettlement | FundingReserveExceeded`
- `estimated_liquidation(position, maintenance) -> LiquidationReference | PathInvalidEvent`

- [ ] Create independent Decimal sign, reserve-slice and LONG/SHORT liquidation references plus TL-14/TL-24.
- [ ] RED-test funding boundary/idempotency, income, remaining release, reserve exceeded pre-commit atomicity, maintenance validity and mandatory watermarks.
- [ ] Implement `ESTIMATED_FIXED_ISOLATED_MARGIN_V1`; fee/funding never alter isolated margin.

## Task 5 — Integrate 2B Entry/Exit planning and Scheduled Exit lifecycle

Interfaces:

- `plan_due_entry_batch(state, due_intents, minute_evidence, planner_dependencies) -> EntryBatchPlanningOutcome`
- `discover_exit_conditions(state, closed_4h, config) -> tuple[ExitConditionSnapshot,...]`
- `plan_due_exits(state, intents, minute_evidence) -> tuple[ExitExecutionPlan|ExecutionRejection,...]`

- [ ] Build a production adapter proving all due BTC/ETH Intents share one AccountPlanningEvidenceBundle/Snapshot, TargetMinuteOpenSnapshot set, completeness snapshot, PortfolioPlanningBatch and PortfolioScalingResult.
- [ ] RED-test RT-25: complete run rejects prefabricated Plan streams and Plans vary with funding/exits before planning.
- [ ] RED-test TIME/TREND/HALT/EXPERIMENT_END source rules, target timing, missing trend evidence, reason priority and cancellation.
- [ ] Invoke existing 2B `position_sizing`, `scale_portfolio` and `build_entry_execution_plan`; do not copy sizing, risk, fee, slippage or contract formulas and do not redistribute after item rejection.
- [ ] Preserve every sizing/batch/scaling/item/Plan/Rejection object. Post-plan cash/risk/evidence conflict is `ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION`, PathInvalidEvent and all-or-none no-Fill; critical exit-planning failure cannot silently become no trade.

## Task 6 — Entry/Scheduled Fill and Position lifecycle

Interfaces:

- `make_entry_fill(plan) -> FillEvent`
- `make_scheduled_exit_fill(plan, matched_reasons) -> FillEvent`
- `apply_position_event(position, event) -> IsolatedPosition | ClosedPosition`

- [ ] Create TL-01, TL-02, TL-05, TL-08, TL-20..23 using actual 2B planner outputs; TL-08 is BTC LONG + ETH SHORT through the real shared batch chain.
- [ ] RED-test expected fill equality, once-only consumption, batch atomicity, one-way position, stable symbol order and experiment-end open.
- [ ] Implement facts and immediately reduce required Ledger entries; no unclosed Fill state.

## Task 7 — stop/TP/open-gap/liquidation and bounded two-path policy

Interfaces:

- `discover_open_gap_candidates(...)`, `discover_intraminute_candidates(...)`
- `resolve_ambiguity(path_kind, parent_state, candidates) -> EngineState`

- [ ] Create TL-03,04,06,07,17..19 and independent formula references before production code.
- [ ] RED-test source separation, `LIQ>STOP>TP>Scheduled` open priority, one-time slippage/tick quantization and one exit per position/minute.
- [ ] RED-test both paths exist from simulation start, economic outputs match before ambiguity, divergence begins no earlier than the first ambiguous minute, and 20 consecutive ambiguities keep exactly two paths with one successor each.
- [ ] Implement policy selection without recursive fork; retain two identities even after state convergence.

## Task 8 — Minute engine, HALT, outputs, Timeline and final verification

Interfaces:

- `process_minute(paths, slice, dependencies) -> tuple[EngineState,...]`
- `run_simulation(inputs, config, dependencies) -> SimulationResult`
- `write_canonical_result(result, directory) -> OutputManifest` (explicit offline output layer only).

- [ ] Freeze all 24 expected Event sequences and a 60-Requirement bidirectional registry; TL-23 HALT drain and TL-24 funding-reserve failure have distinct inputs/hashes.
- [ ] RED-test all 14 order stages, open-exit exposure removal, intraminute conservative exposure, HALT drain, halt/final timestamps, terminal INVALID, byte replay and output identity.
- [ ] Implement pure orchestration and deterministic output; do not add performance metrics.
- [ ] Run all 34 red-team tests and separately report explicit business function count, Property function count, 24 Property IDs, parametrized pytest item count, 24 Timeline, 60 Requirements and 34 Red-Team entries.
- [ ] Run research_cli/data/backtest suites, default full suite baseline comparison, registry validator, Ruff/format, diff check and compileall.
- [ ] Run forbidden-capability scan proving no GUI/LLM/API Key/network/order/2D surface.
- [ ] Create Draft PR and stop for source review; do not start 2D.

## Task dependency closure

`Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8`.

Task 5 depends on the account/funding/liquidation evidence implemented in Tasks 3–4. Task 6 cannot create Fill until Task 3 Ledger is available. Task 8 is the only full-run integration point. There is no forward dependency and no intermediate state in which economic Fill exists without a reducer.

## Authorization and semantic change gate

This plan is authorized for TDD implementation after the four-document cross-audit passes. Any change to Plan-generation timing, Scheduled Exit source rules, `MINUTE_EVENT_ORDER_V2`, funding boundary, gap priority/fill, bounded-path policy, fixed isolated margin, reserve-exceeded behavior, HALT/INVALID semantics or SimulationConfig identity requires a version bump and human review. Completion means Draft PR only; no merge and no 2D.
