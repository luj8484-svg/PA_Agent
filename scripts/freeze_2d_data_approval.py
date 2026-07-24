from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pa_agent.research_2d.approval import (
    freeze_data_approval_manifest,
    sha256_file,
    write_data_approval_manifest,
)


def dependency_lock_hash(project_root: Path) -> str:
    digest = hashlib.sha256()
    for path in (project_root / "pyproject.toml", project_root / "uv.lock"):
        if path.exists():
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze the approved 2D data evidence manifest")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--audit-commit", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = freeze_data_approval_manifest(
        args.root,
        audit_code_commit=args.audit_commit,
        dependency_lock_hash=dependency_lock_hash(args.project_root),
    )
    output = args.root / "data_approval_manifest_v1.json"
    write_data_approval_manifest(output, manifest)
    print(
        json.dumps(
            {"path": str(output), "sha256": sha256_file(output)},
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
