# V1 Failure Attribution — Minimal Implementation Plan

## Objective and boundary

Explain why the frozen V1 core OOS result failed to cover trading costs and assess only H1/H2/H3 as possible, limited future research hypotheses. This work is read-only with respect to the 169 accepted trades and the frozen market data. It must not rerun the event engine, regenerate trades, change 2A/2B/2C, tune V1, implement V2, or add GUI/LLM/API/trading capability.

## Authoritative inputs and fail-closed gate

1. Bind the accepted core OOS experiment `309437824a0abb1611d470d07f91eb1ad69c235dc22027e405fdc89b4b816500`, its result manifest, trades, fills, planning, ledger, daily equity, runtime configuration, corrected archive, approved data manifest, and frozen canonical trade/mark/native 4H/native 1D/funding shards.
2. Verify every manifest-bound file SHA-256 before analysis. Verify frozen data shards against the historical archive manifest, including the canonical content hashes needed by the 169 trade intervals and feature lookbacks.
3. Verify BASELINE and CONSERVATIVE accepted trades are economically identical, exactly 169 unique trades, and reconcile their net PnL and BTC/ETH and LONG/SHORT totals to the corrected archive.
4. On any mismatch, emit `ATTRIBUTION_INPUT_MISMATCH` and stop without producing attribution conclusions.

## Read-only attribution pipeline

1. Parse the accepted BASELINE trades, their entry/exit fills, entry execution plans, sizing records, and original candidate identities. Do not invoke simulation or order-planning functions.
2. Read frozen native 1D/4H and trade/mark 1m records. Recompute only entry-visible descriptive indicators using the frozen V1 algorithms and fixed pre-roll; verify reconstructed Candidate identities against the accepted candidate hash/IDs before using features.
3. Build one immutable attribution row per accepted trade with realized economics, planned stop/target/risk/reward/cost fields, entry-visible trend/breakout/volatility fields, and explicit provenance.
4. Compute direction-correct MFE/MAE from real 1m trade prices during each holding interval. A critical trade/mark gap yields `MFE_MAE_UNAVAILABLE`; no interpolation, forward fill, index substitution, or guessed value is permitted.
5. Analyze TIME_EXIT post-exit 4H/12H/24H behavior only as `POST_HOC_DIAGNOSTIC_ONLY`; it must not enter any strategy input, V1 PnL, or filter.
6. Produce cost, subgroup, odds, profit-concentration, and top-1/top-3/top-5 removal diagnostics from the unchanged accepted trades. Mark every subgroup with fewer than 30 trades `INSUFFICIENT_SUBGROUP_SAMPLE`.
7. Assess H1/H2/H3 with supporting and contradicting evidence, affected count, sample quality, look-ahead risk, complexity, and overfitting risk. At most two may receive `SUPPORTED_FOR_LIMITED_V2_TEST`; this is research authorization only, not a V2 rule.

## Outputs

Write atomically under `artifacts/v1_failure_attribution/`:

- `attribution_manifest.json`
- `trade_attribution.csv`
- `mfe_mae_analysis.csv`
- `time_exit_analysis.csv`
- `cost_attribution.json`
- `subgroup_attribution.json`
- `odds_analysis.json`
- `hypothesis_assessment.json`
- `v1_failure_attribution_report.md`
- a ZIP containing the verified result set

The summary report contains only findings and hashes of detailed artifacts, not duplicated row-level data.

## Verification and stop conditions

Focused tests must cover LONG/SHORT MFE/MAE direction, funding sign, `fees + slippage - funding_cashflow`, planned net R, post-exit isolation, subgroup count = 169, unique trade IDs, strict net-PnL reconciliation, accepted BTC/ETH and LONG/SHORT totals, and fail-closed hash mismatch. Run Ruff, formatting, compileall, and diff checks. Commit only this attribution implementation, tests, plan, and final artifacts; preserve unrelated worktree changes. Stop after delivery without replaying OOS or creating V2 code.

## Self-check

- The plan contains no V1 parameter change, no new trading rule, and no V2 implementation.
- All economics originate from accepted artifacts; all market-path diagnostics originate from frozen canonical data.
- Future prices are restricted to labeled post-hoc explanation and never become strategy inputs.
- Every analysis path is gated by input identity and exact 169-trade reconciliation.
