# V1 Failure Attribution

- Frozen conclusion: `STRATEGY_FAILED_BASELINE_VALIDATION`
- Eligibility: `NOT_LIVE_ELIGIBLE` / `DO_NOT_TRADE`
- Accepted trades reconciled: 169
- Event engine replayed: `false`
- Analysis boundary: `POST_HOC_DIAGNOSTIC_ONLY`

## Cost erosion

- Fees: 150.775458120 USDT
- Slippage: 40.57374866602492077111457400 USDT
- Funding cashflow: -24.7758397568927621730 USDT
- Economic total cost: 216.125046542918 USDT
- Funding income / expense: 6.3900825805476823767 / 31.1659223374404445497 USDT
- Net-winner gross profit / net-loser gross loss: 2037.6425040934485276911 / 2061.1422219703412898641 USDT
- Profitable before cost but loss after cost: 1
- MFE insufficient to cover cost: 7
- Additional average edge for break-even: 0.1390515850703713738047337278 USDT/trade, 0.006965308781563734490625425935R/trade

## MFE/MAE and TIME_EXIT

- Average MFE / MAE: 0.4855597208375312334613112586R / 0.3918655038473561565779978850R
- Reached 0.5R / 1R / 2R / target: 75 / 11 / 0 / 45
- TIME_EXIT classifications: {'EXIT_TOO_EARLY': 8, 'GAVE_BACK_PROFIT': 9, 'INCONCLUSIVE': 9, 'LOSS_LIMITING': 13, 'NO_FOLLOW_THROUGH': 24}
- Trades contributing 80% of gross profit: 39
- Planned net R range: 0.05048778290727152714355672950 to 0.9867549269320045343623834953
- Planned net R conclusion: `NO_DISCRIMINATION_ALL_TRADES_BELOW_1R`

## Hypothesis assessment

- H1: `SUPPORTED_FOR_LIMITED_V2_TEST` — 2 sufficient high-quality groups exceed baseline PF
- H2: `INSUFFICIENT_EVIDENCE` — 17 TIME_EXIT trades show exit-too-early or gave-back-profit diagnostics
- H3: `REJECTED_BY_V1_EVIDENCE` — SHORT PF=0.8983897859641700505625999365; high-trend SHORT PF=0.8203917311490169072115952851

Approved for limited V2 test: `['H1']`

No V2 rule or implementation is created by this report.

## Detailed artifact hashes

- `cost_attribution.json`: `a4b0bd08c226774aaa925a438571001191f78f05c3e8b275af316fc74f6dd79d`
- `hypothesis_assessment.json`: `77e5d9950fd089097132952ff9a599fb9f0a543b0b4d76b0fa62394445961526`
- `mfe_mae_analysis.csv`: `1e9fd904c0ede894dc07ba2ad9bfe6a3754e28b627aade74fdbdd7a096d5404e`
- `odds_analysis.json`: `46a3434cc15a6182a272945aff0b166ad6da68ca12ff2d931426aff515dbdc11`
- `subgroup_attribution.json`: `b6d27b8375582b1ff67ba6bff72ba306ed547887c1643d103ce86a3d86638e64`
- `time_exit_analysis.csv`: `84565e77730a3d6f88c33f570fa6cffb091c8ea2f131b49f452f0303b629d5c8`
- `trade_attribution.csv`: `75dda42eeedbcd49a86e0d689e879e02b30df9eb1ad1f6a6c63d7599f59a92ce`
