from decimal import Decimal

import pytest

from pa_agent.research_v2a.identity import build_threshold_manifest
from pa_agent.research_v2a.thresholds import nearest_rank_threshold
from tests.research_v2a.helpers import make_candidate


def test_nearest_rank_q50_and_q67_do_not_interpolate() -> None:
    strengths = (Decimal("4"), Decimal("1"), Decimal("3"), Decimal("2"))

    assert nearest_rank_threshold(
        strengths, quantile_numerator=1, quantile_denominator=2
    ) == Decimal("2")
    assert nearest_rank_threshold(
        strengths, quantile_numerator=2, quantile_denominator=3
    ) == Decimal("3")


def test_nearest_rank_preserves_ties_and_is_deterministic() -> None:
    strengths = (Decimal("0.5"), Decimal("0.5"), Decimal("2"))

    assert nearest_rank_threshold(
        strengths, quantile_numerator=1, quantile_denominator=2
    ) == Decimal("0.5")
    assert nearest_rank_threshold(
        tuple(reversed(strengths)), quantile_numerator=1, quantile_denominator=2
    ) == Decimal("0.5")


@pytest.mark.parametrize(
    ("strengths", "numerator", "denominator"),
    [
        ((), 1, 2),
        ((Decimal("1"),), 0, 2),
        ((Decimal("1"),), 2, 1),
        ((Decimal("NaN"),), 1, 2),
    ],
)
def test_nearest_rank_invalid_domain_fails_closed(
    strengths: tuple[Decimal, ...], numerator: int, denominator: int
) -> None:
    with pytest.raises(ValueError):
        nearest_rank_threshold(
            strengths,
            quantile_numerator=numerator,
            quantile_denominator=denominator,
        )


def test_threshold_manifest_binds_training_candidates_and_canonical_identity() -> None:
    from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS

    fold = WALK_FORWARD_FOLDS[0]
    candidates = tuple(
        make_candidate(
            decision_time_utc_ms=fold.training_start_utc_ms + index * 14_400_000,
            strength=str(index + 1),
            suffix=hex(index + 10)[2:],
        )
        for index in range(4)
    )

    manifest = build_threshold_manifest(
        fold=fold,
        training_candidates=candidates,
        dataset_content_hash="1" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
    )

    assert manifest.training_candidate_count == 4
    assert manifest.q50 == Decimal("2")
    assert manifest.q67 == Decimal("3")
    assert "generated_at" not in manifest.canonical_json()
    assert len(manifest.content_hash) == 64
    assert manifest == build_threshold_manifest(
        fold=fold,
        training_candidates=tuple(reversed(candidates)),
        dataset_content_hash="1" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
    )


def test_candidate_outside_training_window_fails_closed() -> None:
    from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS

    fold = WALK_FORWARD_FOLDS[0]
    candidate = make_candidate(
        decision_time_utc_ms=fold.validation_start_utc_ms,
        strength="1",
    )

    with pytest.raises(ValueError, match="outside Fold Training"):
        build_threshold_manifest(
            fold=fold,
            training_candidates=(candidate,),
            dataset_content_hash="1" * 64,
            candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
            code_commit="2" * 40,
            dependency_lock_hash="3" * 64,
        )
