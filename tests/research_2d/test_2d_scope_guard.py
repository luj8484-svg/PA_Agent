import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_2d_has_no_network_gui_llm_or_trading_capability() -> None:
    files = (
        *(ROOT / "pa_agent" / "research_2d").glob("*.py"),
        ROOT / "scripts" / "run_2d_baseline_evaluation.py",
    )
    forbidden_import_roots = {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "aiohttp",
        "websockets",
        "PyQt5",
        "PyQt6",
        "openai",
    }
    forbidden_calls = {"create_order", "send_order", "cancel_order"}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name.split(".")[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert not imports & forbidden_import_roots, path
        assert not calls & forbidden_calls, path


def test_frozen_2a_2b_2c_sources_are_not_part_of_branch_diff() -> None:
    changed = subprocess.run(
        ("git", "diff", "--name-only", "fork/main...HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert not any(name.startswith("pa_agent/research_backtest/") for name in changed)
