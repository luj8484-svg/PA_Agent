from __future__ import annotations

import os
from pathlib import Path

import pytest

from pa_agent.research_2d.approval import verify_data_approval_manifest
from pa_agent.research_2d.runner import Split, _load_candidates
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS
from pa_agent.research_v2a.preflight import (
    load_fold_candidate_inputs,
    run_fold_candidate_preflight,
)


@pytest.mark.integration
def test_real_fold_validation_identity_matches_formal_runner_candidate_parameters() -> None:
    configured = os.environ.get("PA_AGENT_REAL_DATA_ROOT")
    if not configured:
        pytest.skip("PA_AGENT_REAL_DATA_ROOT is required for real Candidate handoff test")
    root = Path(configured)
    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    dependency_lock_hash = approval.manifest["dependency_lock_hash"]
    dataset_content_hash = approval.manifest["hybrid_historical_data_bundle_hash"]
    code_commit = "a" * 40

    inputs = load_fold_candidate_inputs(
        root=root,
        folds=WALK_FORWARD_FOLDS,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    report = run_fold_candidate_preflight(
        folds=WALK_FORWARD_FOLDS,
        fold_candidate_inputs=inputs,
        dataset_content_hash=dataset_content_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )

    by_fold = {item.fold_id: item for item in inputs}
    report_by_fold = {item.fold_id: item for item in report.fold_results}
    for fold in WALK_FORWARD_FOLDS:
        formal_candidates, _, _, _ = _load_candidates(
            root,
            Split(
                "TRAINING" if fold.fold_id in {"F1", "F2"} else "VALIDATION",
                fold.validation_start_utc_ms,
                fold.validation_end_utc_ms,
            ),
            "NATIVE_PRIMARY",
            fold.training_start_utc_ms,
            code_commit,
            dependency_lock_hash,
        )
        validation = tuple(formal_candidates)
        preflight_validation = by_fold[fold.fold_id].validation_candidates
        fold_report = report_by_fold[fold.fold_id]

        assert tuple(item.candidate_id for item in preflight_validation) == tuple(
            item.candidate_id for item in validation
        )
        assert canonical_sha256(preflight_validation) == canonical_sha256(validation)
        assert fold_report.validation_candidate_content_hash == canonical_sha256(validation)
        for result in (fold_report.baseline, fold_report.q50, fold_report.q67):
            accepted = tuple(
                item for item in validation if item.candidate_id in result.accepted_candidate_ids
            )
            assert tuple(item.candidate_id for item in accepted) == result.accepted_candidate_ids
            assert canonical_sha256(accepted) == result.accepted_candidate_content_hash
