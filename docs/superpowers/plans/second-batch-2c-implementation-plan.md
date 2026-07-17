# Second-Batch 2C Minimal Event Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest deterministic one-minute BTC/ETH historical execution loop that consumes 2A Candidates and 2B Plans and produces immutable fills, isolated positions, ledger entries, trades, equity points, and VALID/INVALID/HALTED path results.

**Architecture:** A single-threaded pure reducer processes closed one-minute slices under `MINUTE_EVENT_ORDER_V1`. Domain facts are immutable and Canonical; economic state is derived only by reducing Events into Ledger-backed snapshots. Ambiguous intraminute order forks baseline and conservative paths from one parent hash.

**Tech Stack:** Python 3.12, frozen slotted dataclasses, Decimal, pytest, Hypothesis, existing 2B Canonical/identity utilities.

## Global Constraints

- Scope is exactly the 48 Requirements, 16 Timeline Fixtures, and 24 red-team scenarios in the frozen 2C package.
- No GUI, LLM, API Key, authentication, HTTP, create_order, paper/live automation, full performance analytics, walk-forward, OOS, or parameter grids.
- 2C consumes but never mutates/recomputes Candidate, EntryExecutionPlan, ExitExecutionPlan, quantity, or 2B risk formulas.
- Only closed UTC 1m data; trade drives fills/stop/TP, mark drives estimated liquidation/equity, real historical funding drives settlement.
- All economic values use Decimal; outputs are Canonical and byte-stable.
- Every task starts RED, adds an independent reference/fixture before production formulas, ends GREEN, then commits.

## Planned file map

- `pa_agent/research_backtest/simulation/domain.py`: Event, Fill, Position, Ledger, Trade, Equity, Path schemas.
- `pa_agent/research_backtest/simulation/versions.py`: 2C schema/order/model versions only.
- `pa_agent/research_backtest/simulation/inputs.py`: closed-minute and evidence validation.
- `pa_agent/research_backtest/simulation/fills.py`: Plan consumption, gap and protective fill formulas.
- `pa_agent/research_backtest/simulation/funding.py`: real funding settlement.
- `pa_agent/research_backtest/simulation/liquidation.py`: versioned estimated liquidation.
- `pa_agent/research_backtest/simulation/ledger.py`: only account mutation reducer.
- `pa_agent/research_backtest/simulation/ambiguity.py`: baseline/conservative fork selection.
- `pa_agent/research_backtest/simulation/engine.py`: `MINUTE_EVENT_ORDER_V1` orchestration.
- `pa_agent/research_backtest/simulation/output.py`: Canonical JSONL and final hashes.
- `tests/research_backtest/simulation/`: unit/property tests and all Golden timelines.

### Task 1: Closed schemas, versions, Canonical identity, and scope guard

**Interfaces**
- Produces immutable `SimulationConfig`, `MinuteInputSlice`, `SimulationEvent`, `FillEvent`, `IsolatedPosition`, `LedgerEntry`, `AccountState`, `EquityPoint`, `TradeRecord`, `PathResult`.
- Reuses 2B `canonical_dumps`, `canonical_sha256`, `formal_identity` without altering them.

- [ ] Write failing closed-schema, float-rejection, identity-tamper, wall-clock and forbidden-import tests for `2C-ID-*` and `2C-SCOPE-*`.
- [ ] Run `pytest tests/research_backtest/simulation/test_domain_identity_scope.py -v`; expect missing simulation package.
- [ ] Implement only domain/version objects and AST/import-closure guard extensions.
- [ ] Re-run focused tests and existing `tests/research_cli`, `tests/research_data`, `tests/research_backtest/execution`.
- [ ] Commit `feat(research-2c): add simulation domain and scope boundary`.

### Task 2: Input visibility and fail-closed data gate

**Interfaces**
- Consumes Canonical trade/mark/funding rows and due Plans.
- Produces `ValidatedMinuteInputs | PathInvalidEvent` with machine-readable gap provenance.

- [ ] Create TL-10 through TL-13 fixtures and independent expected gap classifier.
- [ ] Write RED tests for closed bars, UTC alignment, future Plan rejection, trade/mark/funding contextual gaps and index audit-only behavior.
- [ ] Implement `validate_minute_inputs(state, slice)` with no filesystem/network access.
- [ ] Verify invalid paths emit no later Event/Ledger/Equity entries.
- [ ] Commit `feat(research-2c): add contextual minute data gate`.

### Task 3: Entry/scheduled-exit fills and isolated positions

**Interfaces**
- `consume_entry_batch(state, plans, trade_open, cost) -> tuple[Event, ...]`
- `consume_scheduled_exits(state, exit_plans, trade_open) -> tuple[Event, ...]`
- `apply_fill(state, FillEvent) -> EngineState` delegates all economics to Task 5 ledger reducer.

- [ ] Create TL-01, TL-02 and TL-08 Plan-bound Golden inputs before production code.
- [ ] Write RED tests for expected fill equality, once-only Plan consumption, batch atomic cash gate, one-way positions and stable BTC/ETH order.
- [ ] Implement Entry/ExitPlan validation and Fill facts; do not implement protective triggers yet.
- [ ] Verify 2B Plan bytes and IDs remain unchanged.
- [ ] Commit `feat(research-2c): consume plans into isolated position fills`.

### Task 4: Fees, real funding, and reserve lifecycle

**Interfaces**
- `settle_funding(position, funding_record, mark_price) -> FundingEvent`
- Fee and funding Events carry Decimal wallet delta; reserves carry separate lock delta.

- [ ] Create TL-05 and TL-14 plus an independent Decimal sign/reference implementation.
- [ ] Write RED tests for four funding sign quadrants, `(pre-minute position, same-time exit, new entry)` boundary, fee once-only and reserve release.
- [ ] Implement fee/funding facts with timestamp idempotency.
- [ ] Property-test that replay/permutation cannot double charge an obligation.
- [ ] Commit `feat(research-2c): settle fees and historical funding once`.

### Task 5: Ledger reducer, account conservation, risk and HALT

**Interfaces**
- `reduce_ledger(previous: AccountState, entries: tuple[LedgerEntry,...]) -> AccountState`
- `mark_equity(state, mark_price) -> EquityPoint`
- Only this task may change wallet/locks/equity fields.

- [ ] Write an independent accounting reference and TL-09/TL-15 expected ledger before implementation.
- [ ] RED-test every ledger kind, wallet/equity/available formulas, margin release, double-use prevention, 0.5%/1% Plan revalidation and 10% open/intraminute/close HALT.
- [ ] Implement reducer invariants after every Event; make HALT absorbing and disallow Entry.
- [ ] Property-test conservation across arbitrary valid event sequences.
- [ ] Commit `feat(research-2c): add conserving account ledger and halt gate`.

### Task 6: stop, TP, gap, and estimated liquidation

**Interfaces**
- `discover_trade_triggers(position, trade_bar) -> TriggerCandidates`
- `discover_liquidation(position, mark_bar, maintenance) -> TriggerCandidate | PathInvalidEvent`
- `protective_fill(candidate, trade_open, cost, contract) -> FillEvent`

- [ ] Create TL-03, TL-04, TL-06, TL-07 and independent Decimal formula references.
- [ ] RED-test source separation, gap reference, one-time slippage/tick quantization, LONG/SHORT liquidation formulas and mmr validity/watermark.
- [ ] Implement trigger discovery without choosing among ambiguous candidates.
- [ ] Verify missing/expired maintenance evidence invalidates held paths.
- [ ] Commit `feat(research-2c): add protective and estimated liquidation triggers`.

### Task 7: ambiguity fork and minute engine

**Interfaces**
- `fork_ambiguous(parent, candidates) -> tuple[BaselinePath, ConservativePath]`
- `process_minute(state, slice) -> tuple[EngineState,...]` is the only orchestration entrypoint.

- [ ] Freeze full expected Event sequences for TL-01 through TL-15.
- [ ] RED-test all 14 `MINUTE_EVENT_ORDER_V1` stages, baseline distance rule, conservative minimum-equity rule, shared parent hash and one exit per position/minute.
- [ ] Implement pure single-threaded orchestration and canonical path sorting.
- [ ] Run all 24 red-team tests; no noncritical naming issue may become a blocker.
- [ ] Commit `feat(research-2c): orchestrate deterministic minute paths`.

### Task 8: outputs, replay determinism, registry and final acceptance

**Interfaces**
- `run_simulation(inputs, config) -> SimulationResult`
- `write_canonical_result(result, directory) -> OutputManifest` writes atomic JSONL through an explicit CLI layer; core reducer remains I/O-free.

- [ ] Create TL-16 byte-for-byte replay fixture and a 48-Requirement bidirectional registry.
- [ ] RED-test TradeRecord required fields, per-minute EquityPoint, path terminal state, atomic output, stable hashes and acquisition-manifest independence.
- [ ] Implement output projection and deterministic manifest; do not add performance metrics.
- [ ] Run `pytest tests/research_backtest/simulation -v`, the entire research suites, registry validator, scoped Ruff/format, diff check and compileall.
- [ ] Run a final forbidden-capability scan proving no GUI/LLM/API Key/network/order surface.
- [ ] Commit `feat(research-2c): complete minimal deterministic replay output` and stop for source review.

## Implementation stop gate

This plan is not authorization to code. Do not create `pa_agent/research_backtest/simulation` or its tests until the four-document package receives explicit human approval. Any semantic change to event order, funding boundary, gap fill, ambiguity selection, ledger formulas, HALT or INVALID behavior requires a version bump and renewed review.
