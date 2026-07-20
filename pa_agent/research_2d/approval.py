from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.simulation.versions import MINUTE_ENGINE_VERSION
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    INDICATOR_CONFIG_VERSION,
    STRATEGY_VERSION,
)

DATA_APPROVAL_MANIFEST_VERSION = "DATA_APPROVAL_MANIFEST_V1"
READY_STATUS = "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS"
APPROVAL_BOUND_FILES = (
    "native_bar_materiality.jsonl",
    "native_bar_materiality_summary.json",
    "candidate_materiality_report.json",
    "mark_gap_materiality.json",
    "experiment_split_candidate_v3.json",
    "final_materiality_report.json",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,64}")


class DataApprovalManifestMismatch(ValueError):
    """The approved data evidence no longer matches its frozen manifest."""


@dataclass(frozen=True, slots=True)
class VerifiedDataApproval:
    root: Path
    manifest: dict[str, Any]
    manifest_hash: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def freeze_data_approval_manifest(
    root: Path,
    *,
    audit_code_commit: str,
    dependency_lock_hash: str,
) -> dict[str, Any]:
    root = root.resolve()
    if _COMMIT_RE.fullmatch(audit_code_commit) is None:
        raise ValueError("audit_code_commit must be 7-64 lowercase hexadecimal characters")
    if _SHA256_RE.fullmatch(dependency_lock_hash) is None:
        raise ValueError("dependency_lock_hash must be 64 lowercase hexadecimal characters")
    readiness = _read_json(root / "final_data_readiness_report.json")
    materiality = _read_json(root / "final_materiality_report.json")
    if materiality.get("final_status") != READY_STATUS:
        raise ValueError("materiality report is not approved for baseline evaluation")
    policy = materiality.get("authority_policy")
    if not isinstance(policy, dict) or not isinstance(policy.get("version"), str):
        raise ValueError("materiality authority policy version is missing")
    mark = materiality.get("mark_gap_materiality")
    native = materiality.get("native_bar_materiality_summary")
    candidate = materiality.get("candidate_materiality")
    if not all(isinstance(value, dict) for value in (mark, native, candidate)):
        raise ValueError("materiality facts are incomplete")
    manifest = {
        "schema_version": DATA_APPROVAL_MANIFEST_VERSION,
        "approval_status": READY_STATUS,
        "hybrid_historical_data_bundle_hash": readiness["data_bundle_hash"],
        "official_archive_bundle_hash": readiness["archive_bundle_hash"],
        "authority_policy_version": policy["version"],
        "bound_file_sha256": {name: sha256_file(root / name) for name in APPROVAL_BOUND_FILES},
        "authenticity_result": materiality["authenticity_totals"],
        "oos_critical_mark_gap_count": mark["oos_critical_mark_gap_count"],
        "price_difference_bar_count": native["price_difference_bar_count"],
        "candidate_direction_change_count": candidate["candidate_direction_changed"],
        "stop_tp_change_count": candidate["stop_or_tp_changed"],
        "versions": {
            "strategy": STRATEGY_VERSION,
            "two_a": INDICATOR_CONFIG_VERSION,
            "two_b": CANONICAL_2B_VERSION,
            "two_c": MINUTE_ENGINE_VERSION,
        },
        "audit_code_commit": audit_code_commit,
        "dependency_lock_hash": dependency_lock_hash,
        "permanent_watermarks": sorted(materiality["permanent_watermarks"]),
    }
    for name in (
        "hybrid_historical_data_bundle_hash",
        "official_archive_bundle_hash",
        "dependency_lock_hash",
    ):
        if _SHA256_RE.fullmatch(manifest[name]) is None:
            raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    return manifest


def write_data_approval_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = canonical_dumps(manifest) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _mismatch(message: str) -> DataApprovalManifestMismatch:
    return DataApprovalManifestMismatch(f"DATA_APPROVAL_MANIFEST_MISMATCH: {message}")


def verify_data_approval_manifest(path: Path) -> VerifiedDataApproval:
    path = path.resolve()
    root = path.parent
    try:
        manifest = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _mismatch(f"cannot read {path.name}") from exc
    if manifest.get("schema_version") != DATA_APPROVAL_MANIFEST_VERSION:
        raise _mismatch("unsupported schema version")
    declared = manifest.get("bound_file_sha256")
    if not isinstance(declared, dict) or set(declared) != set(APPROVAL_BOUND_FILES):
        raise _mismatch("bound file set differs from the frozen approval set")
    for name in APPROVAL_BOUND_FILES:
        target = root / name
        if not target.is_file():
            raise _mismatch(f"missing {name}")
        expected = declared[name]
        if _SHA256_RE.fullmatch(expected) is None or sha256_file(target) != expected:
            raise _mismatch(f"hash mismatch for {name}")
    if manifest.get("approval_status") != READY_STATUS:
        raise _mismatch("approval status is not ready")
    if manifest.get("oos_critical_mark_gap_count") != 0:
        raise _mismatch("OOS critical mark gaps are not zero")
    return VerifiedDataApproval(root, manifest, sha256_file(path))


def verified_output_directory(manifest_path: Path, output: Path) -> Path:
    verify_data_approval_manifest(manifest_path)
    output.mkdir(parents=True, exist_ok=False)
    return output
