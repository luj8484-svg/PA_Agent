from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--collect-only", "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_default_collection_excludes_gui_before_import() -> None:
    result = _collect()
    output = _combined(result)
    assert result.returncode == 0, output
    assert "tests/e2e/test_smoke_free_chat.py" not in output
    assert "tests/unit/test_decision_panel.py" not in output
    assert "GUI files disabled before collection: 14" in output
    assert "legacy e2e files disabled before collection: 4" in output


def test_run_gui_tests_restores_only_non_e2e_gui_modules() -> None:
    result = _collect("--run-gui-tests")
    output = _combined(result)
    assert result.returncode == 0, output
    assert "tests/unit/test_decision_panel.py" in output
    assert "tests/e2e/test_smoke_free_chat.py" not in output


def test_run_legacy_e2e_restores_only_e2e_modules() -> None:
    result = _collect("--run-legacy-e2e")
    output = _combined(result)
    assert result.returncode == 0, output
    assert "tests/e2e/test_smoke_free_chat.py" in output
    assert "tests/unit/test_decision_panel.py" not in output
