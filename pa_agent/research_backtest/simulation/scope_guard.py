from __future__ import annotations

import ast
from pathlib import Path


def scan_simulation_scope(root: Path) -> tuple[str, ...]:
    forbidden_import_roots = {"PyQt6", "requests", "httpx", "socket", "openai"}
    forbidden_names = {"create" + "_order", "api" + "_key"}
    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        if path.name == "scope_guard.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                if names & forbidden_import_roots:
                    violations.append(f"{path.name}:forbidden-import")
            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".")[0]
                if root_name in forbidden_import_roots:
                    violations.append(f"{path.name}:forbidden-import")
            elif isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name.lower() in forbidden_names:
                    violations.append(f"{path.name}:forbidden-name")
    return tuple(sorted(set(violations)))
