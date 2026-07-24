from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from pa_agent.research_backtest.domain.canonical import (
    canonical_dumps,
    canonical_sha256,
)


@dataclass(frozen=True, slots=True)
class PublishedWalkForwardReport:
    output_dir: Path
    canonical_hash: str


def _write_fsynced(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def publish_walk_forward_report(
    *,
    output_dir: Path,
    canonical_economics: object,
    diagnostics: object,
) -> PublishedWalkForwardReport:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    try:
        _write_fsynced(
            temporary / "canonical_report.json",
            canonical_dumps(canonical_economics),
        )
        _write_fsynced(
            temporary / "diagnostics.json",
            canonical_dumps(diagnostics),
        )
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return PublishedWalkForwardReport(
        output_dir=output_dir,
        canonical_hash=canonical_sha256(canonical_economics),
    )
