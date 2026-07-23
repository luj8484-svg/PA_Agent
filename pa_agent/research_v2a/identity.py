from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.strategy.breakout_strength import (
    calculate_breakout_strength,
)
from pa_agent.research_v2a.domain import StrategyIdentity, WalkForwardFold
from pa_agent.research_v2a.thresholds import nearest_rank_threshold

THRESHOLD_MANIFEST_SCHEMA_VERSION = "V2A_THRESHOLD_MANIFEST_V1"
EXPERIMENT_IDENTITY_SCHEMA_VERSION = "V2A_EXPERIMENT_IDENTITY_V1"
THRESHOLD_CALCULATION_VERSION = "V2A_NEAREST_RANK_GLOBAL_Q50_Q67_V1"
BREAKOUT_STRENGTH_VERSION = "BREAKOUT_STRENGTH_DECIMAL_V1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{7,64}")


@dataclass(frozen=True, slots=True)
class ThresholdManifest:
    schema_version: str
    fold_id: str
    training_start_utc_ms: int
    training_end_utc_ms: int
    training_candidate_content_hash: str
    training_candidate_count: int
    quantile_rule: str
    q50: Decimal
    q67: Decimal
    dataset_content_hash: str
    candidate_filter_version: str
    breakout_strength_version: str
    threshold_calculation_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != THRESHOLD_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported threshold manifest schema")
        if self.fold_id not in {"F1", "F2", "F3", "F4"}:
            raise ValueError("unsupported Fold identity")
        if self.training_candidate_count <= 0:
            raise ValueError("training Candidate count must be positive")
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value < 0
            for value in (self.q50, self.q67)
        ):
            raise ValueError("thresholds must be finite nonnegative Decimal values")
        for name in (
            "training_candidate_content_hash",
            "dataset_content_hash",
            "threshold_calculation_hash",
            "dependency_lock_hash",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if _COMMIT.fullmatch(self.code_commit) is None:
            raise ValueError("code_commit must be a hexadecimal commit identity")
        if not self.candidate_filter_version:
            raise ValueError("candidate_filter_version must be nonempty")

    def canonical_json(self) -> str:
        return canonical_dumps(self)

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    schema_version: str
    strategy_identities: tuple[StrategyIdentity, ...]
    fold_manifest_hashes: tuple[str, ...]
    threshold_manifest_hashes: tuple[str, ...]
    threshold_calculation_hashes: tuple[str, ...]
    dataset_content_hash: str
    code_commit: str
    dependency_lock_hash: str
    candidate_filter_version: str
    computational_experiment_id: str

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def _ordered_candidates(
    candidates: tuple[StrategyCandidate, ...],
) -> tuple[StrategyCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (item.decision_time_utc_ms, item.symbol, item.candidate_id),
        )
    )


def build_threshold_manifest(
    *,
    fold: WalkForwardFold,
    training_candidates: tuple[StrategyCandidate, ...],
    dataset_content_hash: str,
    candidate_filter_version: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> ThresholdManifest:
    ordered = _ordered_candidates(training_candidates)
    if not ordered:
        raise ValueError("Training Candidate collection must be nonempty")
    if any(
        not fold.training_start_utc_ms <= candidate.decision_time_utc_ms <= fold.training_end_utc_ms
        for candidate in ordered
    ):
        raise ValueError("Candidate is outside Fold Training")
    strengths = tuple(
        calculate_breakout_strength(
            market_view=candidate.market_view,
            decision_close=candidate.decision_close,
            prior_20_bar_donchian_upper=candidate.donchian_high_previous_20,
            prior_20_bar_donchian_lower=candidate.donchian_low_previous_20,
            decision_atr_4h=candidate.atr14_4h,
        )
        for candidate in ordered
    )
    candidate_hash = canonical_sha256(ordered)
    q50 = nearest_rank_threshold(strengths, quantile_numerator=1, quantile_denominator=2)
    q67 = nearest_rank_threshold(strengths, quantile_numerator=2, quantile_denominator=3)
    calculation_hash = canonical_sha256(
        {
            "version": THRESHOLD_CALCULATION_VERSION,
            "breakout_strength_version": BREAKOUT_STRENGTH_VERSION,
            "training_candidate_content_hash": candidate_hash,
            "training_candidate_count": len(ordered),
            "quantiles": (("Q50", 1, 2, q50), ("Q67", 2, 3, q67)),
        }
    )
    return ThresholdManifest(
        schema_version=THRESHOLD_MANIFEST_SCHEMA_VERSION,
        fold_id=fold.fold_id,
        training_start_utc_ms=fold.training_start_utc_ms,
        training_end_utc_ms=fold.training_end_utc_ms,
        training_candidate_content_hash=candidate_hash,
        training_candidate_count=len(ordered),
        quantile_rule="NEAREST_RANK_INDEX_CEIL_Q_TIMES_N_MINUS_1_V1",
        q50=q50,
        q67=q67,
        dataset_content_hash=dataset_content_hash,
        candidate_filter_version=candidate_filter_version,
        breakout_strength_version=BREAKOUT_STRENGTH_VERSION,
        threshold_calculation_hash=calculation_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )


def build_experiment_identity(
    *,
    strategy_identities: tuple[StrategyIdentity, ...],
    fold_manifest_hashes: tuple[str, ...],
    threshold_manifests: tuple[ThresholdManifest, ...],
    dataset_content_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
    candidate_filter_version: str,
) -> ExperimentIdentity:
    if not strategy_identities or StrategyIdentity.V1_BASELINE not in strategy_identities:
        raise ValueError("experiment identities must include V1_BASELINE")
    if len(set(strategy_identities)) != len(strategy_identities):
        raise ValueError("strategy identities must be unique")
    if any(_SHA256.fullmatch(value) is None for value in fold_manifest_hashes):
        raise ValueError("fold manifest hashes must be SHA-256 values")
    threshold_hashes = tuple(manifest.content_hash for manifest in threshold_manifests)
    calculation_hashes = tuple(
        manifest.threshold_calculation_hash for manifest in threshold_manifests
    )
    payload = {
        "schema_version": EXPERIMENT_IDENTITY_SCHEMA_VERSION,
        "strategy_identities": strategy_identities,
        "fold_manifest_hashes": fold_manifest_hashes,
        "threshold_manifest_hashes": threshold_hashes,
        "threshold_calculation_hashes": calculation_hashes,
        "dataset_content_hash": dataset_content_hash,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
        "candidate_filter_version": candidate_filter_version,
    }
    experiment_id = canonical_sha256(payload)
    return ExperimentIdentity(
        **payload,
        computational_experiment_id=experiment_id,
    )
