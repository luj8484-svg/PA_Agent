import ast
from pathlib import Path

PACKAGE = Path("pa_agent/research_backtest")
SECOND_BATCH_2A_PATHS = (
    PACKAGE / "domain" / "candidates.py",
    PACKAGE / "domain" / "canonical.py",
    PACKAGE / "domain" / "failures.py",
    PACKAGE / "domain" / "validation.py",
    PACKAGE / "indicators",
    PACKAGE / "strategy",
)

FORBIDDEN_PARTS = {
    "execution",
    "risk",
    "events",
    "ledger",
    "reporting",
    "margin",
    "positions",
    "matching",
    "llm",
    "gui",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "pa_agent.ai",
    "pa_agent.gui",
    "pa_agent.indicators",
    "pa_agent.orchestrator",
    "openai",
    "requests",
    "httpx",
    "urllib",
    "socket",
)
FORBIDDEN_SOURCE_TOKENS = (
    "create_order(",
    "api_key",
    "secret",
    "/account",
    "/order",
    "contract_rule",
    "funding_settlement",
    "liquidation",
)


def _second_batch_2a_python_files():
    for path in SECOND_BATCH_2A_PATHS:
        if path.is_dir():
            yield from path.rglob("*.py")
        else:
            yield path


def test_2a_contains_no_forbidden_modules_or_directories():
    violations = []
    for path in _second_batch_2a_python_files():
        if FORBIDDEN_PARTS.intersection(part.lower() for part in path.parts):
            violations.append(str(path))
    assert violations == []


def test_2a_imports_only_pure_or_first_batch_model_dependencies():
    violations = []
    for path in _second_batch_2a_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.startswith(FORBIDDEN_IMPORT_PREFIXES) for name in names):
                violations.append((str(path), names))
    assert violations == []


def test_2a_source_has_no_execution_network_account_or_credential_tokens():
    source = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in _second_batch_2a_python_files()
    )
    assert [token for token in FORBIDDEN_SOURCE_TOKENS if token in source] == []
