from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MODULE_PREFIXES = (
    "PyQt5",
    "PyQt6",
    "pa_agent.main",
    "pa_agent.gui",
    "pa_agent.app_context",
    "pa_agent.ai",
)


def _sanitized_environment() -> dict[str, str]:
    forbidden_fragments = ("API_KEY", "SECRET_KEY", "TOKEN", "PASSWORD")
    return {
        key: value
        for key, value in os.environ.items()
        if not any(fragment in key.upper() for fragment in forbidden_fragments)
    }


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=_sanitized_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_import_does_not_load_gui_llm_or_pyqt() -> None:
    probe = (
        "import json,sys; import pa_agent.research_cli; "
        f"prefixes={FORBIDDEN_MODULE_PREFIXES!r}; "
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name.startswith(prefixes))))"
    )
    result = _run("-c", probe)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_help_is_side_effect_free_without_keys() -> None:
    result = _run("-m", "pa_agent.research_cli", "--help")
    assert result.returncode == 0, result.stderr
    assert "version" in result.stdout
    assert "validate-environment" in result.stdout
    assert "configure API Key" not in result.stdout + result.stderr


def test_version_reports_research_cli_version() -> None:
    result = _run("-m", "pa_agent.research_cli", "version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pa-research 0.1.0"


def test_validate_environment_imports_only_research_roots() -> None:
    result = _run("-m", "pa_agent.research_cli", "validate-environment")
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "research_data=OK" in output
    assert "research_backtest=OK" in output
    assert "llm_api_key_required=no" in output
    assert "exchange_api_key_required=no" in output
    assert "network_access=not_performed" in output
    assert "python=" in output
    assert "dependency.pa-agent=" in output
    assert "dependency.numpy=" in output
    assert "dependency.pandas=" in output
