import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "3a5583598122236904c5a0919f8eb5740b6d6c54"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_research_2d_does_not_depend_on_research_v2a() -> None:
    for path in (ROOT / "pa_agent" / "research_2d").glob("*.py"):
        assert not any(name.startswith("pa_agent.research_v2a") for name in _imports(path)), path


def test_v2a_has_no_pnl_post_exit_gui_llm_network_or_trading_dependency() -> None:
    forbidden_imports = {
        "pa_agent.research_2d.attribution",
        "requests",
        "httpx",
        "socket",
        "PyQt5",
        "PyQt6",
        "openai",
    }
    forbidden_tokens = {
        "trade_attribution",
        "MFE",
        "MAE",
        "create_order",
        "send_order",
    }
    for path in (ROOT / "pa_agent" / "research_v2a").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not (_imports(path) & forbidden_imports), path
        assert not any(token in source for token in forbidden_tokens), path


def test_only_authorized_shared_file_changes_research_backtest() -> None:
    commands = (
        ("git", "diff", "--name-only", f"{BASELINE}...HEAD"),
        ("git", "diff", "--name-only"),
        ("git", "ls-files", "--others", "--exclude-standard"),
    )
    changed = {
        name
        for command in commands
        for name in subprocess.run(
            command, cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.splitlines()
    }
    protected = {
        name
        for name in changed
        if name.startswith("pa_agent/research_backtest/")
        and name != "pa_agent/research_backtest/strategy/breakout_strength.py"
    }
    assert not protected
