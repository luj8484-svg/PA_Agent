from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.simulation.domain import PathState
from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent


@dataclass(frozen=True, slots=True)
class PathResult:
    path_state: PathState
    final_processed_time_utc_ms: int
    invalid_reason: str | None = None
    halt_trigger_time_utc_ms: int | None = None
    halt_reason: str | None = None
    entry_disabled: bool = False
    flat_after_halt_time_utc_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SimulationProjection:
    events: tuple[object, ...]
    ledger_entries: tuple[object, ...]
    trades: tuple[object, ...]
    equity_points: tuple[object, ...]
    path_result: PathResult


def terminal_invalid_projection(event: PathInvalidEvent) -> SimulationProjection:
    result = PathResult(
        path_state=PathState.INVALID,
        final_processed_time_utc_ms=event.event_time_utc_ms,
        invalid_reason=event.reason,
    )
    return SimulationProjection((event,), (), (), (), result)


@dataclass(frozen=True, slots=True)
class OutputManifest:
    schema_version: str
    result_content_hash: str
    path_count: int
    minute_result_count: int
    file_hashes: tuple[tuple[str, str], ...] = ()


def output_manifest(result: object) -> OutputManifest:
    paths = result.paths
    return OutputManifest(
        schema_version="SIMULATION_OUTPUT_MANIFEST_V1",
        result_content_hash=canonical_sha256(result),
        path_count=len(paths),
        minute_result_count=sum(len(path.minute_results) for path in paths),
    )


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _jsonl(rows: list[object]) -> str:
    return "".join(f"{canonical_dumps(row)}\n" for row in rows)


def write_canonical_result(result: object, output_directory: str | Path) -> OutputManifest:
    """Atomically persist the deterministic 2C result projections."""
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list[object]] = {
        "events.jsonl": [],
        "fills.jsonl": [],
        "ledger.jsonl": [],
        "planning.jsonl": [],
        "positions.jsonl": [],
        "trades.jsonl": [],
        "equity.jsonl": [],
        "path_results.jsonl": [],
    }
    for path in result.paths:
        for minute in path.minute_results:
            rows["events.jsonl"].extend(minute.events)
            rows["fills.jsonl"].extend(minute.fills)
            rows["ledger.jsonl"].extend(minute.ledger_entries)
            rows["planning.jsonl"].extend(minute.planning_outputs)
            rows["positions.jsonl"].append(
                {
                    "event_time_utc_ms": minute.state.final_processed_time_utc_ms,
                    "path_kind": path.path_kind,
                    "positions": minute.state.positions,
                }
            )
            rows["trades.jsonl"].extend(minute.trades)
            rows["equity.jsonl"].extend(minute.equity_points)
        rows["path_results.jsonl"].append(path.path_result)

    hashes: list[tuple[str, str]] = []
    for filename in sorted(rows):
        content = _jsonl(rows[filename])
        _atomic_write(directory / filename, content)
        hashes.append((filename, hashlib.sha256(content.encode("utf-8")).hexdigest()))

    base = output_manifest(result)
    manifest = OutputManifest(
        base.schema_version,
        base.result_content_hash,
        base.path_count,
        base.minute_result_count,
        tuple(hashes),
    )
    _atomic_write(directory / "manifest.json", canonical_dumps(manifest) + "\n")
    return manifest
