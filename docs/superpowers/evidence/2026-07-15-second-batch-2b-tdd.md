# Second-Batch 2B TDD Evidence

## Task 1 — Canonical, registry, and scope foundations

- RED command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_registry_canonical_scope.py -q`
- RED result: collection failed with `ModuleNotFoundError: pa_agent.research_backtest.domain.base`, proving the new identity/registry/scope behavior did not exist before implementation.
- GREEN command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_registry_canonical_scope.py -q`
- GREEN result: `13 passed`; the five-source parser independently reports `435` documented IDs, `435` unique IDs, and `114` bound Requirements. The real-suite validator intentionally reports documented-but-not-yet-implemented IDs until Task 10.

## Task 2 — Entry intent, execution time, and open/watermark evidence

- RED command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_entry_intent_time_market.py -q`
- RED result: collection failed with `ModuleNotFoundError: pa_agent.research_backtest.domain.config`, proving EntryIntent, execution-time config, and target-open evidence did not exist.
- GREEN command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_entry_intent_time_market.py -q`
- GREEN result: `13 passed`; exact 4H anchors and 0/1/2-minute targets, closed EntryIntent/Open schemas, independent watermark evidence, missing-target handling, and consumption-time identity invariance passed.

## Task 3 — Contract, cost, funding schedule, and funding risk

- RED command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_contract_cost_funding.py -q`
- RED result: collection failed with `ModuleNotFoundError: pa_agent.research_backtest.domain.contracts`, after the independent funding-window reference was present and before production formulas existed.
- GREEN command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_contract_cost_funding.py -q`
- GREEN result: `27 passed`; contract tagged unions/gates, cost snapshots, explicit funding windows, `(entry,maxExit]`, coverage fail-closed behavior, independent funding-risk evidence, and the seven-window 48h reference comparison passed.

## Task 4 — Account snapshot and evidence bundle

- RED command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_account_evidence.py -q`
- RED result: collection failed with `ModuleNotFoundError: pa_agent.research_backtest.domain.accounts`, after the independent account arithmetic reference existed and before any account evidence implementation.
- GREEN command: `.\.venv\Scripts\python.exe -m pytest tests/research_backtest/execution/unit/test_account_evidence.py -q`
- GREEN result: `8 passed`; bundle closure, exact eligible-time valuation, wallet/equity/available-balance replay, open-risk and pending collection replay, missing evidence failure, and immutable snapshot construction passed against the independent Decimal reference.
