# Binance Historical Data Readiness

Final status after materiality reclassification: `READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS`

- Pre-materiality status: `DATA_INTEGRITY_FAILED` (preserved as coarse audit history only).
- Authority policy: `BINANCE_OFFICIAL_SOURCE_AUTHORITY_V1`; native 4H/1D is the 2A source, aggregated 4H/1D is audit-only.
- Issue bars: `62`; differing fields: `303`.
- Audit-only bars: `58`; price-difference bars: `4`.
- Candidate direction changes: `0`; quantized stop/TP changes: `13`.
- OOS critical mark gaps: `0`.
- Full evidence: `final_materiality_report.json`.
- Permanent watermarks: `APPROXIMATED_EXECUTION_INFRASTRUCTURE, OFFICIAL_SOURCE_PRODUCT_DISAGREEMENT, NOT_EXCHANGE_EXACT, NOT_LIVE_ELIGIBLE`.
- No historical redownload, no 2A/2B/2C modification, no full 2D, no API key or trading capability.
