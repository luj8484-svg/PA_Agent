from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_IMPORTS = (
    "curl",
    "http",
    "httpx",
    "openai",
    "requests",
    "socket",
    "subprocess",
    "urllib",
    "websocket",
)
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "getenv",
    "import_module",
    "open",
    "read_bytes",
    "read_text",
    "system",
    "write_bytes",
    "write_text",
}
BUILTIN_ONLY_FORBIDDEN_CALLS = {"__import__", "compile", "eval", "exec"}
FORBIDDEN_NAMES = {
    "api_key",
    "create_order",
    "drawdown",
    "fill_event",
    "funding_settlement",
    "ledger",
    "liquidation",
    "mutate_account",
    "performance_report",
    "private_key",
}


@dataclass(frozen=True, slots=True)
class ScopeViolation:
    path: str
    line: int
    detail: str


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _local_import_path(module_name: str, package_root: Path) -> Path | None:
    leaf = module_name.rsplit(".", 1)[-1]
    candidate = package_root / f"{leaf}.py"
    return candidate if candidate.exists() else None


def scan_forbidden_capabilities(
    entry_paths: tuple[Path, ...],
    *,
    package_root: Path,
) -> tuple[ScopeViolation, ...]:
    pending = list(entry_paths)
    visited: set[Path] = set()
    violations: list[ScopeViolation] = []
    while pending:
        path = pending.pop()
        resolved = path.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = (node.module or "",)
            else:
                modules = ()
            for module in modules:
                if module.startswith(FORBIDDEN_IMPORTS):
                    violations.append(ScopeViolation(str(path), node.lineno, module))
                local_path = _local_import_path(module, package_root)
                if local_path is not None:
                    pending.append(local_path)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if lowered in FORBIDDEN_NAMES:
                    violations.append(ScopeViolation(str(path), node.lineno, lowered))
            if isinstance(node, ast.Call):
                name = _qualified_name(node.func)
                leaf = name.rsplit(".", 1)[-1]
                if leaf in FORBIDDEN_CALLS and not (
                    leaf in BUILTIN_ONLY_FORBIDDEN_CALLS and "." in name
                ):
                    violations.append(ScopeViolation(str(path), node.lineno, name))
                if name in {"datetime.now", "datetime.utcnow", "time.time"}:
                    violations.append(ScopeViolation(str(path), node.lineno, name))
    return tuple(sorted(violations, key=lambda item: (item.path, item.line, item.detail)))
