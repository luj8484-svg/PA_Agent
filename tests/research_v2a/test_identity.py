from dataclasses import replace

from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS, StrategyIdentity
from pa_agent.research_v2a.identity import (
    build_experiment_identity,
    build_threshold_manifest,
)
from tests.research_v2a.helpers import make_candidate

HORIZON_IDENTITY = {
    "execution_horizon_gate_version": "V2A_EXECUTION_HORIZON_GATE_V1",
    "execution_time_config_content_hash": "5" * 64,
    "maximum_holding_minutes": 2880,
    "max_hold_version": "MAX_HOLD_V1_EXACT_48H",
    "execution_horizon_decision_hashes": ("6" * 64,),
}


def _manifest(strength: str = "1"):
    fold = WALK_FORWARD_FOLDS[0]
    return build_threshold_manifest(
        fold=fold,
        training_candidates=(
            make_candidate(
                decision_time_utc_ms=fold.training_start_utc_ms,
                strength=strength,
            ),
        ),
        dataset_content_hash="1" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
    )


def test_experiment_identity_is_canonical_and_binds_threshold_manifest() -> None:
    manifest = _manifest()
    identity = build_experiment_identity(
        strategy_identities=(
            StrategyIdentity.V1_BASELINE,
            StrategyIdentity.V2A_Q50,
            StrategyIdentity.V2A_Q67,
        ),
        fold_manifest_hashes=("4" * 64,),
        threshold_manifests=(manifest,),
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        **HORIZON_IDENTITY,
    )

    assert len(identity.computational_experiment_id) == 64
    assert (
        identity.canonical_json()
        == build_experiment_identity(
            strategy_identities=identity.strategy_identities,
            fold_manifest_hashes=identity.fold_manifest_hashes,
            threshold_manifests=(manifest,),
            dataset_content_hash="1" * 64,
            code_commit="2" * 40,
            dependency_lock_hash="3" * 64,
            candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
            **HORIZON_IDENTITY,
        ).canonical_json()
    )


def test_threshold_change_changes_experiment_identity() -> None:
    original = _manifest("1")
    changed = replace(original, q50=original.q50 + 1)

    first = build_experiment_identity(
        strategy_identities=(StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50),
        fold_manifest_hashes=("4" * 64,),
        threshold_manifests=(original,),
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        **HORIZON_IDENTITY,
    )
    second = build_experiment_identity(
        strategy_identities=first.strategy_identities,
        fold_manifest_hashes=first.fold_manifest_hashes,
        threshold_manifests=(changed,),
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        **HORIZON_IDENTITY,
    )

    assert first.computational_experiment_id != second.computational_experiment_id


def test_execution_horizon_decision_change_changes_experiment_identity() -> None:
    manifest = _manifest()
    first = build_experiment_identity(
        strategy_identities=(StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50),
        fold_manifest_hashes=("4" * 64,),
        threshold_manifests=(manifest,),
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        **HORIZON_IDENTITY,
    )
    changed = build_experiment_identity(
        strategy_identities=first.strategy_identities,
        fold_manifest_hashes=first.fold_manifest_hashes,
        threshold_manifests=(manifest,),
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        **{
            **HORIZON_IDENTITY,
            "execution_horizon_decision_hashes": ("7" * 64,),
        },
    )

    assert first.computational_experiment_id != changed.computational_experiment_id
