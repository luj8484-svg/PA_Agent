# Second-Batch 2D Baseline Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a deterministic, approval-gated BTCUSDT/ETHUSDT baseline historical evaluation using the frozen 2A candidates, 2B planning rules, and 2C minute engine, with native 4H/1D as the formal authority and aggregated bars as sensitivity only.

**Architecture:** Add a read-only `research_2d` orchestration package around the existing 2A/2B/2C public interfaces. The orchestration verifies immutable audit evidence before it creates any performance output, streams local Canonical market data into split-scoped engine inputs, executes native and aggregated authorities through the same economic chain, then writes compact deterministic reports and detailed CSV artifacts locally. Existing `pa_agent/research_backtest` modules remain byte-for-byte unchanged.

**Tech Stack:** CPython 3.12.13, standard library, Decimal, NumPy/Pandas already declared by the project, pytest, Ruff, existing PA Agent 2A/2B/2C domain APIs.

## Global Constraints

- Do not download historical data or access the network.
- Do not modify any file under `pa_agent/research_backtest`; 2A, 2B, and 2C are frozen dependencies.
- Do not add API keys, authenticated exchange access, account access, GUI, LLM decisions, HTTP clients, `create_order`, paper trading, or live trading.
- Native Binance trade 4H/1D is the only formal 2A authority; 1m aggregation is sensitivity only.
- Trade 1m, mark 1m, and real funding are the only 2C market inputs; index data is audit only.
- Baseline and conservative paths are reported separately.
- Missing approval files or hash mismatch stops with `DATA_APPROVAL_MANIFEST_MISMATCH` before any performance file is written.
- Formal conclusion uses only NATIVE_PRIMARY OOS and is one of the four authorized conclusion values.
- Large historical data and runtime result directories remain ignored and are not uploaded to GitHub.

---

### Task 1: Freeze Audit Identity Inputs

**Files:**
- Modify: `.gitignore`
- Create: `artifacts/historical_data_readiness/experiment_split_candidate_v3.json`
- Create: `tests/research_2d/test_identity.py`
- Create: `pa_agent/research_2d/__init__.py`
- Create: `pa_agent/research_2d/identity.py`

**Interfaces:**
- Produces: `build_split_candidate_v3(v2: Mapping[str, object]) -> dict[str, object]`
- Produces: `build_experiment_identity_payload(manifest: Mapping[str, object]) -> dict[str, object]`
- Produces: `computational_experiment_id(payload: Mapping[str, object]) -> str`

- [ ] **Step 1: Write failing identity tests**

```python
def test_v3_renames_short_identity_without_claiming_full_experiment_id():
    value = build_split_candidate_v3(V2)
    assert value["version"] == "EXPERIMENT_SPLIT_CANDIDATE_V3"
    assert value["split_candidate_id"] == V2["computational_experiment_id"]
    assert "computational_experiment_id" not in value

def test_experiment_id_is_canonical_sha256_and_sensitive_to_every_dependency():
    baseline = computational_experiment_id(PAYLOAD)
    assert re.fullmatch(r"[0-9a-f]{64}", baseline)
    for key in PAYLOAD:
        assert computational_experiment_id(PAYLOAD | {key: f"changed:{PAYLOAD[key]}"}) != baseline
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run: `python -m pytest tests/research_2d/test_identity.py -v`
Expected: collection failure because `pa_agent.research_2d.identity` does not exist.

- [ ] **Step 3: Implement canonical V3 and experiment identity**

Use existing `pa_agent.research_backtest.domain.canonical.canonical_sha256`; reject missing dependency names, unknown names, non-SHA hash fields, prefixed IDs, and non-canonical version strings. The experiment payload contains approved bundle hash, approval hash, split hash, authority policy, strategy/2A/2B/planner/2C/fee/slippage/funding/contract/maintenance/path versions, code commit, and dependency lock hash.

- [ ] **Step 4: Generate V3 and rerun identity tests**

Run: `python -m pytest tests/research_2d/test_identity.py -v`
Expected: all tests pass.

- [ ] **Step 5: Ignore runtime-only data and result directories**

Keep audit summaries and the approval manifest trackable; ignore `artifacts/data_readiness/refreshed/**`, `artifacts/historical_data_readiness/data/**`, and `artifacts/research_2d/**`.

### Task 2: Freeze and Verify the Unique Data Approval Manifest

**Files:**
- Create: `pa_agent/research_2d/approval.py`
- Create: `tests/research_2d/test_approval.py`
- Create: `scripts/freeze_2d_data_approval.py`
- Create: `artifacts/historical_data_readiness/data_approval_manifest_v1.json`

**Interfaces:**
- Produces: `freeze_data_approval_manifest(root: Path, audit_commit: str, dependency_lock_hash: str) -> dict[str, object]`
- Produces: `verify_data_approval_manifest(path: Path) -> VerifiedDataApproval`
- Raises: `DataApprovalManifestMismatch("DATA_APPROVAL_MANIFEST_MISMATCH: ...")`

- [ ] **Step 1: Write failing tests for exact file binding and fail-closed behavior**

```python
def test_verifier_rehashes_every_bound_file(tmp_path):
    manifest = freeze_fixture(tmp_path)
    assert verify_data_approval_manifest(manifest).manifest_hash == sha256_file(manifest)
    bound_file(tmp_path).write_text("tampered", encoding="utf-8")
    with pytest.raises(DataApprovalManifestMismatch, match="DATA_APPROVAL_MANIFEST_MISMATCH"):
        verify_data_approval_manifest(manifest)

def test_failure_creates_no_performance_directory(tmp_path):
    with pytest.raises(DataApprovalManifestMismatch):
        preflight_and_prepare_output(tampered_manifest(tmp_path), tmp_path / "results")
    assert not (tmp_path / "results").exists()
```

- [ ] **Step 2: Run tests and confirm expected failure**

Run: `python -m pytest tests/research_2d/test_approval.py -v`
Expected: failure because approval functions are absent.

- [ ] **Step 3: Implement manifest freeze and verification**

Bind both bundle hashes, authority policy, SHA256 of six approved audit files including V3, authenticity result, OOS critical mark-gap count, price/candidate/stop-TP materiality counts, frozen 2A/2B/2C versions, audit commit, dependency lock hash, and permanent watermarks. Canonicalize with the existing deterministic serializer and use atomic write.

- [ ] **Step 4: Run approval tests and generate the real manifest**

Run: `python scripts/freeze_2d_data_approval.py --root artifacts/historical_data_readiness --audit-commit <AUDIT_SHA>`
Expected: writes one `data_approval_manifest_v1.json` and prints its lowercase SHA256.

### Task 3: Load Approved Historical Inputs Without Network Access

**Files:**
- Create: `pa_agent/research_2d/data.py`
- Create: `tests/research_2d/test_data.py`

**Interfaces:**
- Produces: `iter_canonical_records(root, symbol, stream, start_ms, end_ms)`
- Produces: `load_strategy_bars(authority, symbol, split) -> StrategyBars`
- Produces: `iter_minute_slices(symbols, split, funding_multiplier) -> Iterator[MinuteInputSlice]`
- Produces: `build_candidates(authority, split, code_commit, dependency_hash) -> tuple[StrategyCandidate, ...]`

- [ ] **Step 1: Write failing tests using tiny monthly JSONL fixtures**

Cover closed-bar enforcement, UTC boundaries, deterministic month ordering, exact Decimal preservation, native versus aggregated selection, real funding timestamps/rates, and index exclusion.

- [ ] **Step 2: Run the tests and confirm missing-loader failure**

Run: `python -m pytest tests/research_2d/test_data.py -v`

- [ ] **Step 3: Implement streaming readers and candidate construction**

Convert Canonical records to existing `Kline`, `MinuteBar`, and `FundingRecord` types. Build a Candidate on every closed 4H decision using the existing `build_candidate`; keep only LONG/SHORT for execution while counting NO_SETUP and ValidationFailure. Never synthesize a missing mark/trade/funding record.

- [ ] **Step 4: Run loader tests and a bounded real-data smoke read**

Run: `python -m pytest tests/research_2d/test_data.py -v`
Expected: all tests pass; smoke output reports exact first/last timestamps without network access.

### Task 4: Adapt Frozen Evidence Into the 2C Production Context

**Files:**
- Create: `pa_agent/research_2d/evidence.py`
- Create: `tests/research_2d/test_evidence.py`

**Interfaces:**
- Produces: `build_evidence_catalog(request: EvaluationRequest, candidates, market_index) -> SimulationEvidenceCatalog`
- Produces: `build_simulation_inputs(request, candidates, market_index) -> SimulationInputs`
- Produces: `run_split_scenario(request: EvaluationRequest) -> SimulationResult`

- [ ] **Step 1: Write failing integration tests against real 2A/2B/2C factories**

Assert target opens use only the scheduled trade-minute open, historical contracts are explicitly APPROXIMATED, maintenance is ESTIMATED, fee/slippage values are frozen, funding schedules cover the split, and both baseline/conservative paths execute through `run_production_simulation`.

- [ ] **Step 2: Run tests and confirm missing adapter failure**

Run: `python -m pytest tests/research_2d/test_evidence.py -v`

- [ ] **Step 3: Implement the adapter without modifying frozen modules**

Use 1x leverage, isolated/one-way mode, initial wallet `10000`, entry/exit delay `1m`, fee `0.0005`, BTC slippage `0.0001`, ETH slippage `0.0002`, current-rule APPROXIMATED contract evidence, estimated maintenance evidence, and observed funding records. Scenario overrides alter cost evidence or funding records only and remain named in the experiment manifest.

- [ ] **Step 4: Run adapter integration tests**

Run: `python -m pytest tests/research_2d/test_evidence.py -v`

### Task 5: Compute Metrics, Benchmarks, Gap Impact, and Sensitivity

**Files:**
- Create: `pa_agent/research_2d/metrics.py`
- Create: `pa_agent/research_2d/benchmarks.py`
- Create: `pa_agent/research_2d/gaps.py`
- Create: `tests/research_2d/test_metrics.py`
- Create: `tests/research_2d/test_gaps.py`

**Interfaces:**
- Produces: `summarize_path(result, split, authority, scenario) -> dict[str, object]`
- Produces: `benchmark_metrics(strategy_bars, split) -> dict[str, object]`
- Produces: `reconcile_authorities(native, aggregated) -> dict[str, object]`
- Produces: `mark_gap_impact(gaps, path_runs) -> dict[str, object]`

- [ ] **Step 1: Write failing Golden metric tests**

Use fixed trades/equity to assert initial/final capital, return, annualization, maximum drawdown and dates, Sharpe, Sortino, Calmar, win rate, profit factor, average payoff, trade/BTC/ETH/LONG/SHORT counts, holding duration, fee/slippage/funding/total cost, HALT, INVALID, and rejection categories. Test zero-denominator output as explicit `null` plus reason.

- [ ] **Step 2: Write failing gap and authority reconciliation tests**

Assert every approved gap reports position, EntryIntent, scheduled exit, plans, trades, invalid episodes; assert no gap is silently dropped and OOS critical gap count remains zero. Assert sensitivity includes actual trade/fill/stop/TP/net-return/drawdown/affected-trade differences.

- [ ] **Step 3: Implement deterministic metrics and benchmarks**

Daily equity is UTC close sampled from actual 2C equity. Benchmarks are equal-weight BTC/ETH buy-and-hold and the frozen 200-day trend rule. The conclusion gate reads only NATIVE_PRIMARY OOS.

- [ ] **Step 4: Run metrics and gap tests**

Run: `python -m pytest tests/research_2d/test_metrics.py tests/research_2d/test_gaps.py -v`

### Task 6: Orchestrate the Full Evaluation and Write Required Artifacts

**Files:**
- Create: `pa_agent/research_2d/runner.py`
- Create: `pa_agent/research_2d/report.py`
- Create: `scripts/run_2d_baseline_evaluation.py`
- Create: `tests/research_2d/test_runner.py`
- Create: `tests/research_2d/test_scope_guard.py`

**Interfaces:**
- Produces: `run_baseline_evaluation(config: EvaluationConfig) -> EvaluationOutcome`
- Produces all twelve required files under `artifacts/research_2d/<computational_experiment_id>/`.

- [ ] **Step 1: Write failing end-to-end fixture tests**

Assert preflight precedes output creation, Training/Validation/OOS × Native/Aggregated × Baseline/Conservative are present, cost scenarios are present, summary embeds only aggregates and file path/hash references, and result manifest rehashes every output.

- [ ] **Step 2: Write failing scope-guard tests**

Scan new code for network clients, API keys, GUI imports, LLM imports, order/account endpoints, `create_order`, and writes under `pa_agent/research_backtest`.

- [ ] **Step 3: Implement atomic orchestration and reports**

Verify approval first; freeze experiment manifest; compute its 64-hex ID; create a temporary output directory; run all scenarios; write files; fsync; atomically rename. On any invalid approval, emit only the exception and no performance directory.

- [ ] **Step 4: Run 2D tests and frozen regression suites**

Run: `python -m pytest tests/research_2d -v`
Run: `python -m pytest tests/research_data tests/research_backtest -q`
Expected: all 2D, research-data, 2A, 2B, and 2C tests pass.

### Task 7: Run the Approved 66-Month Evaluation

**Files:**
- Runtime only: `artifacts/research_2d/<computational_experiment_id>/*`

- [ ] **Step 1: Commit implementation before evaluating**

Record the source commit and use it as the experiment manifest `code_commit`; do not put runtime result files into that commit.

- [ ] **Step 2: Execute the formal run**

Run: `python scripts/run_2d_baseline_evaluation.py --data-root artifacts/historical_data_readiness --output-root artifacts/research_2d`
Expected: complete Training, Validation, and OOS results for native and aggregated authorities plus four cost scenarios, or an authorized fail-closed conclusion with precise evidence.

- [ ] **Step 3: Re-run determinism validation**

Run the same command to a second temporary output root and compare `result_manifest.json` and all deterministic file hashes.

- [ ] **Step 4: Inspect result invariants**

Verify the 64-hex ID, approval hash, six native/aggregated path groups, OOS no critical mark gap, actual gap impacts, benchmarks, stress results, and authorized conclusion.

### Task 8: Verify, Review, Publish a Draft PR, and Stop

**Files:**
- Modify only files already listed in Tasks 1–6 if review finds a tested defect.

- [ ] **Step 1: Run fresh complete verification**

Run:

```powershell
python -m pytest tests/research_2d -v
python -m pytest tests/research_cli -q
python -m pytest tests/research_data -q
python -m pytest tests/research_backtest/execution -q
python -m pytest tests/research_backtest/simulation -q
python -m pytest tests/research_backtest -q
python scripts/validate_2b_test_registry.py
ruff check pa_agent/research_2d tests/research_2d scripts/freeze_2d_data_approval.py scripts/run_2d_baseline_evaluation.py
ruff format --check pa_agent/research_2d tests/research_2d scripts/freeze_2d_data_approval.py scripts/run_2d_baseline_evaluation.py
git diff --check fork/main...HEAD
python -m compileall -q pa_agent
```

- [ ] **Step 2: Perform source review and scope comparison**

Confirm `git diff --name-only fork/main...HEAD` contains no `pa_agent/research_backtest/**` file and no large data/result file. Review identity coverage, fail-closed ordering, cost semantics, gap denominators, native-only conclusion, and deterministic hashes.

- [ ] **Step 3: Push and create Draft PR**

Push `feature/second-batch-2d-baseline-evaluation` to the fork and create a Draft PR against fork `main`. Report local test evidence and explicitly state cloud CI status rather than inferring it.

- [ ] **Step 4: Stop**

Do not merge main, start forward simulation, start live trading, configure API keys, or begin any later phase.

## Self-Review

- Spec coverage: both preflights, native authority, aggregated sensitivity, gap context, metrics, benchmarks, stress, artifacts, conclusion enum, security boundary, and Draft PR each map to a task.
- Placeholder scan: no TBD/TODO/implement-later steps remain.
- Type consistency: identity, approval, data, evidence, metrics, runner, and report interfaces form a one-way dependency chain; 2A/2B/2C remain imports only.
- Scope split decision: kept as one plan because the user explicitly authorized both preflight closures and 2D execution in the same task and required a single Draft PR.
