# Deterministic Research CLI

The deterministic BTC/ETH research path is deliberately isolated from the legacy PA Agent desktop application.

## Safe research commands

These commands do not start PyQt, load GUI modules, initialize an LLM client, inspect API keys, authenticate to an exchange, or place orders:

```powershell
python -m pa_agent.research_cli --help
python -m pa_agent.research_cli version
python -m pa_agent.research_cli validate-environment
pa-research --help
```

`validate-environment` performs local imports and reports Python/package versions. It does not access the network and reports that neither an LLM API key nor an exchange API key is required.

## Legacy GUI boundary

The following are explicit legacy GUI entry points:

```powershell
python run.py
python -m pa_agent.main
pa-agent
pa-agent-gui
```

Research commands and research automation **must not use legacy GUI entry points**. The legacy GUI remains available for its original use, but it is not part of `pa_agent.research_data`, `pa_agent.research_backtest`, or the research CLI import chain.

## Pytest collection boundary

Default pytest collection excludes known PyQt/GUI and legacy GUI e2e modules before importing their Python files. The test session prints the number of excluded paths.

Explicit collection is available only when intentionally requested:

```powershell
python -m pytest --run-gui-tests
python -m pytest --run-legacy-e2e
```

- `--run-gui-tests` enables the 14 known non-e2e GUI test modules.
- `--run-legacy-e2e` enables the 4 legacy GUI e2e modules.
- The flags are independent; passing one does not enable the other category.

Markers named `gui` and `legacy_e2e` document the same boundary, but safety is enforced by pre-collection path exclusion rather than post-import markers or skips.

## V1 scope

The CLI currently provides only help, version reporting, and local environment validation. It does not implement a minute event engine, fills, position changes, funding settlement, liquidation, ledger accounting, PnL, performance reports, paper trading, live trading, or automated order placement.
