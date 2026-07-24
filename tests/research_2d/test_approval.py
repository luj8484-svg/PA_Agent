from __future__ import annotations

import json
from pathlib import Path

import pytest

from pa_agent.research_2d.approval import (
    APPROVAL_BOUND_FILES,
    DataApprovalManifestMismatch,
    freeze_data_approval_manifest,
    sha256_file,
    verified_output_directory,
    verify_data_approval_manifest,
    write_data_approval_manifest,
)


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
    )


def approval_root(tmp_path: Path) -> Path:
    root = tmp_path / "historical_data_readiness"
    root.mkdir()
    for name in APPROVAL_BOUND_FILES:
        _write(root / name, {"name": name})
    _write(
        root / "final_data_readiness_report.json",
        {
            "data_bundle_hash": "1" * 64,
            "archive_bundle_hash": "2" * 64,
        },
    )
    _write(
        root / "final_materiality_report.json",
        {
            "final_status": "READY_FOR_BASELINE_EVALUATION_WITH_APPROXIMATIONS",
            "authenticity_totals": {"matched": 588, "mismatched": 0},
            "authority_policy": {"version": "BINANCE_OFFICIAL_SOURCE_AUTHORITY_V1"},
            "mark_gap_materiality": {"oos_critical_mark_gap_count": 0},
            "native_bar_materiality_summary": {"price_difference_bar_count": 4},
            "candidate_materiality": {
                "candidate_direction_changed": 0,
                "stop_or_tp_changed": 13,
            },
            "permanent_watermarks": [
                "APPROXIMATED_EXECUTION_INFRASTRUCTURE",
                "NOT_EXCHANGE_EXACT",
                "NOT_LIVE_ELIGIBLE",
                "OFFICIAL_SOURCE_PRODUCT_DISAGREEMENT",
            ],
        },
    )
    return root


def test_freeze_binds_every_required_file_and_approved_fact(tmp_path: Path) -> None:
    root = approval_root(tmp_path)

    manifest = freeze_data_approval_manifest(
        root,
        audit_code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )

    assert manifest["schema_version"] == "DATA_APPROVAL_MANIFEST_V1"
    assert set(manifest["bound_file_sha256"]) == set(APPROVAL_BOUND_FILES)
    assert manifest["hybrid_historical_data_bundle_hash"] == "1" * 64
    assert manifest["official_archive_bundle_hash"] == "2" * 64
    assert manifest["authenticity_result"] == {"matched": 588, "mismatched": 0}
    assert manifest["oos_critical_mark_gap_count"] == 0
    assert manifest["price_difference_bar_count"] == 4
    assert manifest["candidate_direction_change_count"] == 0
    assert manifest["stop_tp_change_count"] == 13
    assert manifest["audit_code_commit"] == "a" * 40
    assert manifest["dependency_lock_hash"] == "b" * 64
    assert manifest["versions"]["two_c"] == "MINUTE_ENGINE_V1"


def test_verifier_rehashes_every_bound_file(tmp_path: Path) -> None:
    root = approval_root(tmp_path)
    manifest = freeze_data_approval_manifest(
        root,
        audit_code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )
    path = root / "data_approval_manifest_v1.json"
    write_data_approval_manifest(path, manifest)

    verified = verify_data_approval_manifest(path)
    assert verified.manifest_hash == sha256_file(path)
    assert verified.root == root

    (root / "candidate_materiality_report.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(DataApprovalManifestMismatch, match="DATA_APPROVAL_MANIFEST_MISMATCH"):
        verify_data_approval_manifest(path)


def test_verifier_rejects_missing_bound_file(tmp_path: Path) -> None:
    root = approval_root(tmp_path)
    manifest = freeze_data_approval_manifest(
        root,
        audit_code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )
    path = root / "data_approval_manifest_v1.json"
    write_data_approval_manifest(path, manifest)
    (root / "mark_gap_materiality.json").unlink()

    with pytest.raises(DataApprovalManifestMismatch, match=r"mark_gap_materiality\.json"):
        verify_data_approval_manifest(path)


def test_failure_creates_no_performance_directory(tmp_path: Path) -> None:
    root = approval_root(tmp_path)
    manifest = freeze_data_approval_manifest(
        root,
        audit_code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )
    path = root / "data_approval_manifest_v1.json"
    write_data_approval_manifest(path, manifest)
    (root / "native_bar_materiality_summary.json").write_text("{}\n", encoding="utf-8")
    output = tmp_path / "results"

    with pytest.raises(DataApprovalManifestMismatch):
        verified_output_directory(path, output)
    assert not output.exists()


def test_manifest_writer_is_canonical_and_atomic(tmp_path: Path) -> None:
    root = approval_root(tmp_path)
    manifest = freeze_data_approval_manifest(
        root,
        audit_code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
    )
    path = root / "data_approval_manifest_v1.json"

    write_data_approval_manifest(path, manifest)

    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert content == json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n"
    assert not path.with_suffix(".json.tmp").exists()
