# Research CLI Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a side-effect-free research CLI and prevent default pytest collection from importing legacy GUI/e2e modules.

**Architecture:** Keep the legacy GUI intact behind explicit `run.py`, `pa-agent`, and `pa-agent-gui` entry points. Add a standard-library-only `pa_agent.research_cli` dispatcher, and use root-level `pytest_ignore_collect` hooks to exclude known GUI and legacy e2e paths before Python imports them unless an explicit opt-in flag is present.

**Tech Stack:** Python 3.11+, argparse, importlib, pytest hooks, subprocess acceptance tests, setuptools console scripts.

## Global Constraints

- Base commit is fork `main` at `872ba56eef5df409842c9ad6326626ae287c6161`.
- Branch is `chore/research-cli-isolation`; no commit may enter PR #2.
- Do not modify first-batch data behavior, 2A indicators/Candidate, or any 2B formula, Schema, Intent, Plan, sizing, scaling, risk, cost, or funding behavior.
- Do not implement 2C, Fill, position mutation, funding settlement, liquidation, ledger, PnL, reports, GUI behavior, LLM configuration, API keys, authenticated exchange access, HTTP trading, or automatic ordering.
- The research CLI must not read, print, write, or require secrets.
- String scanning is secondary evidence; real subprocess import and collection tests are mandatory.

---

## Root-cause record

The legacy GUI chain is:

```text
run.py
  -> pa_agent.main
  -> PyQt6.QtWidgets.QApplication
  -> pa_agent.app_context.AppContext.bootstrap()
  -> pa_agent.gui.main_window.MainWindow
```

The deterministic research packages do not start the GUI. The observed windows were created by two concurrent unrestricted `pytest -q` runs that collected legacy GUI/e2e tests. Runtime PIDs are transient evidence and are intentionally not persisted here.

### Legacy e2e modules that construct `AppContext` and `MainWindow`, then call `show()`

- `tests/e2e/test_smoke_free_chat.py`
- `tests/e2e/test_smoke_happy_path.py`
- `tests/e2e/test_smoke_no_order.py`
- `tests/e2e/test_smoke_switch_mid_flight.py`

### Other GUI-importing modules that must be excluded before collection by default

- `tests/integration/test_next_bar_prediction.py`
- `tests/integration/test_switch_mid_analysis.py`
- `tests/property/test_next_bar_prediction_perf.py`
- `tests/unit/test_chart_decision_overlay.py`
- `tests/unit/test_chart_fit_view.py`
- `tests/unit/test_chart_skip_redraw.py`
- `tests/unit/test_chart_widget_no_lines_when_not_trading.py`
- `tests/unit/test_debug_widget_masks_key.py`
- `tests/unit/test_decision_panel.py`
- `tests/unit/test_order_opportunity.py`
- `tests/unit/test_overlay_lines.py`
- `tests/unit/test_support_resistance_chart.py`
- `tests/unit/test_token_indicator_thresholds.py`
- `tests/unit/test_validation_retry.py`

These modules directly or function-locally import PyQt, `pa_agent.gui`, or `AppContext`. Several construct `QApplication`, `MainWindow`, widgets, or call `show()`; `MainWindow` construction can start GUI refresh/worker paths and expose legacy API-key configuration UI. A marker applied after import is therefore too late.

---

### Task 1: Freeze pre-collection isolation behavior

**Files:**
- Create: `tests/research_cli/test_pytest_precollection.py`
- Create: `tests/research_cli/__init__.py`
- Create: `conftest.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: pytest `pytest_addoption`, `pytest_ignore_collect`, and `pytest_sessionstart` hooks.
- Produces: `--run-gui-tests`, `--run-legacy-e2e`, registered `gui`/`legacy_e2e` markers, and deterministic excluded-path reporting.

- [ ] **Step 1: Write failing subprocess collection tests**

```python
def test_default_collection_excludes_gui_before_import(run_pytest):
    result = run_pytest("--collect-only", "-q")
    assert result.returncode == 0
    assert "tests/e2e/test_smoke_free_chat.py" not in result.stdout
    assert "tests/unit/test_decision_panel.py" not in result.stdout
    assert "GUI files disabled before collection: 14" in result.stdout
    assert "legacy e2e files disabled before collection: 4" in result.stdout
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_cli/test_pytest_precollection.py -v`

Expected: FAIL because the opt-in flags and pre-collection exclusions do not exist.

- [ ] **Step 3: Implement the root hook**

```python
GUI_TEST_FILES = frozenset({...14 exact POSIX paths...})
LEGACY_E2E_PREFIX = "tests/e2e/"

def pytest_addoption(parser):
    parser.addoption("--run-gui-tests", action="store_true", default=False)
    parser.addoption("--run-legacy-e2e", action="store_true", default=False)

def pytest_ignore_collect(collection_path, config):
    relative = collection_path.relative_to(Path(str(config.rootpath))).as_posix()
    if relative.startswith(LEGACY_E2E_PREFIX):
        return not config.getoption("--run-legacy-e2e")
    if relative in GUI_TEST_FILES:
        return not config.getoption("--run-gui-tests")
    return None
```

Add an always-visible `pytest_sessionstart` line reporting disabled file counts, and register `gui` and `legacy_e2e` markers in `pyproject.toml`.

- [ ] **Step 4: Run GREEN and explicit collection checks**

Run:

```powershell
python -m pytest tests/research_cli/test_pytest_precollection.py -v
python -m pytest --collect-only -q
python -m pytest --run-gui-tests --collect-only -q
python -m pytest --run-legacy-e2e --collect-only -q
```

Expected: default excludes all 18 paths before import; each opt-in flag restores only its controlled category.

- [ ] **Step 5: Commit**

```text
test(research-cli): freeze pre-collection GUI isolation
```

### Task 2: Add the side-effect-free research CLI

**Files:**
- Create: `pa_agent/research_cli.py`
- Create: `tests/research_cli/test_research_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`, `pa-research`, `version`, and `validate-environment`.
- Imports at module load: Python standard library only.

- [ ] **Step 1: Write failing CLI and import-closure tests**

```python
def test_import_does_not_load_gui_or_pyqt(run_python):
    result = run_python("import sys; import pa_agent.research_cli; print('\\n'.join(sys.modules))")
    assert result.returncode == 0
    assert "PyQt6" not in result.stdout
    assert "pa_agent.main" not in result.stdout
    assert "pa_agent.app_context" not in result.stdout

def test_help_requires_no_keys_and_leaves_no_child_process(run_cli):
    result = run_cli("--help", sanitized_environment=True)
    assert result.returncode == 0
    assert "API Key" not in result.stderr
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_cli/test_research_cli.py -v`

Expected: FAIL with `No module named pa_agent.research_cli`.

- [ ] **Step 3: Implement minimal standard-library CLI**

```python
def validate_environment() -> int:
    importlib.import_module("pa_agent.research_data")
    importlib.import_module("pa_agent.research_backtest")
    print(f"python={platform.python_version()}")
    print("research_data=OK")
    print("research_backtest=OK")
    print("llm_api_key_required=no")
    print("exchange_api_key_required=no")
    print("network_access=not_performed")
    return 0
```

Add `pa-research = "pa_agent.research_cli:main"` and explicit legacy `pa-agent-gui = "pa_agent.main:main"`; retain `pa-agent` compatibility.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest tests/research_cli/test_research_cli.py -v
python -m pa_agent.research_cli --help
python -m pa_agent.research_cli version
python -m pa_agent.research_cli validate-environment
```

Expected: all commands exit 0 without GUI, network access, credentials, or child processes.

- [ ] **Step 5: Commit**

```text
feat(research-cli): add side-effect-free research entrypoint
```

### Task 3: Add defense-in-depth scope guards and usage documentation

**Files:**
- Create: `tests/research_cli/test_research_cli_scope.py`
- Create: `docs/research_cli.md`
- Modify: `README.md`
- Modify: `Makefile`

**Interfaces:**
- Produces: source/import guard and documented separation between research and legacy GUI commands.

- [ ] **Step 1: Write failing source and process-safety tests**

Assert the CLI source/import closure contains none of `create_order`, `API_KEY`, `SECRET_KEY`, `requests`, `httpx`, `aiohttp`, `websocket`, `PyQt`, `pa_agent.main`, `pa_agent.gui`, or `pa_agent.app_context`; monkeypatch socket creation and prove `validate-environment` does not access the network.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_cli/test_research_cli_scope.py -v`

Expected: FAIL until the guard fixtures and documentation contracts exist.

- [ ] **Step 3: Document and expose safe commands**

Document:

```text
python -m pa_agent.research_cli --help
python -m pa_agent.research_cli version
python -m pa_agent.research_cli validate-environment
pa-research --help
```

State that `run.py`, `pa-agent`, and `pa-agent-gui` are legacy GUI paths and must never be used by research automation. Add `research-help`, `research-version`, and `research-validate` Make targets without changing GUI business logic.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/research_cli -v`

Expected: all isolation tests pass.

- [ ] **Step 5: Commit**

```text
docs(research-cli): document deterministic research boundary
```

### Task 4: Full regression, runtime audit, and independent Draft PR

**Files:**
- Verify only; modify no production behavior.

**Interfaces:**
- Produces: complete command/result record, process/window counts, pushed branch, and independent Draft PR.

- [ ] **Step 1: Capture pre-run GUI window and relevant Python child-process counts**

Use Windows process metadata, matching only the repository/worktree path and `PA Agent — Trading Terminal`; do not inspect environment variables or credentials.

- [ ] **Step 2: Run the complete verification matrix**

```powershell
python -m pa_agent.research_cli --help
python -m pa_agent.research_cli version
python -m pa_agent.research_cli validate-environment
python -m pytest tests/research_data -v
python -m pytest tests/research_backtest -v
python -m pytest -v
python -m pytest --collect-only -q
python -m pytest --run-gui-tests --collect-only -q
python -m pytest --run-legacy-e2e --collect-only -q
python -m ruff check .
python -m ruff format --check .
git diff --check
python -m compileall -q pa_agent
```

Compare any legacy full-suite failures with fork main; introduce no new non-GUI failure.

- [ ] **Step 3: Capture post-run process/window counts and scope diff**

Expected: no GUI windows, no remaining research CLI/test Python child process, no first-batch/2A/2B/2C business files changed.

- [ ] **Step 4: Final verification commit if documentation-only evidence changes are necessary**

```text
chore(research-cli): finalize isolation verification
```

- [ ] **Step 5: Push and create Draft PR**

Push `chore/research-cli-isolation` to fork and create a Draft PR against `main` titled `chore: isolate research CLI from legacy GUI`. Stop after creation; do not merge.

## Plan self-review

- Spec coverage: independent branch, root-cause paths, CLI, explicit GUI entry, pre-collection blocking, subprocess tests, security scan, full verification, and Draft PR are covered.
- Placeholder scan: no TBD/TODO or deferred implementation exists.
- Scope check: no research data, strategy, execution, backtest engine, GUI business, LLM, key, or trading behavior is modified.
- Type consistency: the CLI exposes one `main` and three commands; pytest flags and path ownership are defined once in the root hook.
