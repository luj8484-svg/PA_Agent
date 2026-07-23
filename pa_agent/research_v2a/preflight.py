from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.approval import verify_data_approval_manifest
from pa_agent.research_2d.runner import Split, _load_candidates
from pa_agent.research_backtest.domain.candidates import StrategyCandidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_v2a.breakout_quality import (
    CANDIDATE_FILTER_VERSION,
    CandidateFilterOutcome,
    filter_candidate,
)
from pa_agent.research_v2a.domain import (
    WALK_FORWARD_FOLDS,
    StrategyIdentity,
    WalkForwardFold,
)
from pa_agent.research_v2a.identity import (
    ExperimentIdentity,
    ThresholdManifest,
    build_experiment_identity,
    build_threshold_manifest,
)

PREFLIGHT_SCHEMA_VERSION = "V2A_CANDIDATE_PREFLIGHT_V1"
PREFLIGHT_PASSED = "PASS"
PREFLIGHT_FAILED = "V2A_PREFLIGHT_FAILED"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{7,64}")


@dataclass(frozen=True, slots=True)
class CandidatePreflightStrategyResult:
    strategy_identity: StrategyIdentity
    threshold: Decimal | None
    validation_candidate_count: int
    accepted_candidate_count: int
    rejected_candidate_count: int
    retention_rate: Decimal
    accepted_by_symbol: tuple[tuple[str, int], ...]
    accepted_by_side: tuple[tuple[str, int], ...]
    accepted_candidate_ids: tuple[str, ...]
    accepted_candidate_content_hash: str


@dataclass(frozen=True, slots=True)
class FoldPreflightResult:
    fold_id: str
    training_candidate_count: int
    training_candidate_content_hash: str
    threshold_manifest_hash: str
    validation_candidate_count: int
    validation_candidate_content_hash: str
    baseline: CandidatePreflightStrategyResult
    q50: CandidatePreflightStrategyResult
    q67: CandidatePreflightStrategyResult


@dataclass(frozen=True, slots=True)
class CandidatePreflightReport:
    schema_version: str
    status: str
    dataset_content_hash: str
    candidate_content_hash: str
    candidate_count: int
    candidate_filter_version: str
    code_commit: str
    dependency_lock_hash: str
    fold_results: tuple[FoldPreflightResult, ...]
    eligible_strategies: tuple[StrategyIdentity, ...]
    eligible_task_count: int
    elimination_reasons: tuple[str, ...]

    def canonical_json(self) -> str:
        return canonical_dumps(self)

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class CandidatePreflightBundle:
    report: CandidatePreflightReport
    experiment_identity: ExperimentIdentity
    fold_candidate_inputs: tuple[FoldCandidateInputs, ...]


@dataclass(frozen=True, slots=True)
class FoldCandidateInputs:
    fold_id: str
    training_candidates: tuple[StrategyCandidate, ...]
    validation_candidates: tuple[StrategyCandidate, ...]


def _ordered(
    candidates: tuple[StrategyCandidate, ...],
) -> tuple[StrategyCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (item.decision_time_utc_ms, item.symbol, item.candidate_id),
        )
    )


def _result(
    *,
    strategy: StrategyIdentity,
    threshold: Decimal | None,
    validation_candidates: tuple[StrategyCandidate, ...],
) -> CandidatePreflightStrategyResult:
    if threshold is None:
        accepted = validation_candidates
    else:
        accepted = tuple(
            decision.candidate
            for candidate in validation_candidates
            if (
                decision := filter_candidate(
                    candidate,
                    threshold=threshold,
                    candidate_filter_version=CANDIDATE_FILTER_VERSION,
                )
            ).outcome
            is CandidateFilterOutcome.ACCEPT
        )
    symbols = Counter(candidate.symbol for candidate in accepted)
    sides = Counter(candidate.market_view.value for candidate in accepted)
    total = len(validation_candidates)
    return CandidatePreflightStrategyResult(
        strategy_identity=strategy,
        threshold=threshold,
        validation_candidate_count=total,
        accepted_candidate_count=len(accepted),
        rejected_candidate_count=total - len(accepted),
        retention_rate=Decimal(len(accepted)) / Decimal(total) if total else Decimal("0"),
        accepted_by_symbol=tuple((name, symbols[name]) for name in ("BTCUSDT", "ETHUSDT")),
        accepted_by_side=tuple((name, sides[name]) for name in ("LONG", "SHORT")),
        accepted_candidate_ids=tuple(candidate.candidate_id for candidate in accepted),
        accepted_candidate_content_hash=canonical_sha256(accepted),
    )


def _elimination_reasons(
    strategy: StrategyIdentity,
    results: tuple[CandidatePreflightStrategyResult, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for fold_index, result in enumerate(results, start=1):
        if result.accepted_candidate_count < 15:
            reasons.append(f"{strategy.value}:F{fold_index}:ACCEPTED_LT_15")
        if any(count == 0 for _, count in result.accepted_by_symbol):
            reasons.append(f"{strategy.value}:F{fold_index}:SYMBOL_DELETED")
        if any(count == 0 for _, count in result.accepted_by_side):
            reasons.append(f"{strategy.value}:F{fold_index}:SIDE_DELETED")
    if sum(result.accepted_candidate_count for result in results) < 80:
        reasons.append(f"{strategy.value}:TOTAL_ACCEPTED_LT_80")
    return tuple(reasons)


def _fold_result(
    *,
    fold: WalkForwardFold,
    training_candidates: tuple[StrategyCandidate, ...],
    validation_candidates: tuple[StrategyCandidate, ...],
    dataset_content_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> tuple[
    FoldPreflightResult,
    ThresholdManifest,
    CandidatePreflightStrategyResult,
    CandidatePreflightStrategyResult,
]:
    training = _ordered(training_candidates)
    validation = _ordered(validation_candidates)
    if not training or not validation:
        raise ValueError(f"{fold.fold_id}: Training and Validation Candidates must be nonempty")
    if any(
        not fold.training_start_utc_ms <= candidate.decision_time_utc_ms <= fold.training_end_utc_ms
        for candidate in training
    ):
        raise ValueError(f"{fold.fold_id}: Candidate is outside Fold Training")
    if any(
        not fold.validation_start_utc_ms
        <= candidate.decision_time_utc_ms
        <= fold.validation_end_utc_ms
        for candidate in validation
    ):
        raise ValueError(f"{fold.fold_id}: Candidate is outside Fold Validation")
    manifest = build_threshold_manifest(
        fold=fold,
        training_candidates=training,
        dataset_content_hash=dataset_content_hash,
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    baseline = _result(
        strategy=StrategyIdentity.V1_BASELINE,
        threshold=None,
        validation_candidates=validation,
    )
    q50 = _result(
        strategy=StrategyIdentity.V2A_Q50,
        threshold=manifest.q50,
        validation_candidates=validation,
    )
    q67 = _result(
        strategy=StrategyIdentity.V2A_Q67,
        threshold=manifest.q67,
        validation_candidates=validation,
    )
    return (
        FoldPreflightResult(
            fold_id=fold.fold_id,
            training_candidate_count=len(training),
            training_candidate_content_hash=manifest.training_candidate_content_hash,
            threshold_manifest_hash=manifest.content_hash,
            validation_candidate_count=len(validation),
            validation_candidate_content_hash=canonical_sha256(validation),
            baseline=baseline,
            q50=q50,
            q67=q67,
        ),
        manifest,
        q50,
        q67,
    )


def run_fold_candidate_preflight(
    *,
    folds: tuple[WalkForwardFold, ...],
    fold_candidate_inputs: tuple[FoldCandidateInputs, ...],
    dataset_content_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> CandidatePreflightReport:
    if tuple(fold.fold_id for fold in folds) != ("F1", "F2", "F3", "F4"):
        raise ValueError("Preflight requires the four frozen Walk-forward Folds")
    if tuple(item.fold_id for item in fold_candidate_inputs) != ("F1", "F2", "F3", "F4"):
        raise ValueError("Fold Candidate inputs must be ordered F1 through F4")
    if _SHA256.fullmatch(dataset_content_hash) is None:
        raise ValueError("dataset_content_hash must be a lowercase SHA-256")
    if _SHA256.fullmatch(dependency_lock_hash) is None:
        raise ValueError("dependency_lock_hash must be a lowercase SHA-256")
    if _COMMIT.fullmatch(code_commit) is None:
        raise ValueError("code_commit must be a hexadecimal commit identity")

    built = tuple(
        _fold_result(
            fold=fold,
            training_candidates=inputs.training_candidates,
            validation_candidates=inputs.validation_candidates,
            dataset_content_hash=dataset_content_hash,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
        for fold, inputs in zip(folds, fold_candidate_inputs, strict=True)
    )
    fold_results = tuple(item[0] for item in built)
    q50_results = tuple(item[2] for item in built)
    q67_results = tuple(item[3] for item in built)
    q50_reasons = _elimination_reasons(StrategyIdentity.V2A_Q50, q50_results)
    q67_reasons = _elimination_reasons(StrategyIdentity.V2A_Q67, q67_results)
    surviving = tuple(
        strategy
        for strategy, reasons in (
            (StrategyIdentity.V2A_Q50, q50_reasons),
            (StrategyIdentity.V2A_Q67, q67_reasons),
        )
        if not reasons
    )
    eligible = (StrategyIdentity.V1_BASELINE, *surviving) if surviving else ()
    diagnostic_candidates = _ordered(
        tuple(
            candidate
            for inputs in fold_candidate_inputs
            for candidate in (*inputs.training_candidates, *inputs.validation_candidates)
        )
    )
    return CandidatePreflightReport(
        schema_version=PREFLIGHT_SCHEMA_VERSION,
        status=PREFLIGHT_PASSED if surviving else PREFLIGHT_FAILED,
        dataset_content_hash=dataset_content_hash,
        candidate_content_hash=canonical_sha256(diagnostic_candidates),
        candidate_count=len(diagnostic_candidates),
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
        fold_results=fold_results,
        eligible_strategies=eligible,
        eligible_task_count=4 * len(eligible),
        elimination_reasons=(*q50_reasons, *q67_reasons),
    )


def run_candidate_preflight(
    *,
    folds: tuple[WalkForwardFold, ...],
    strategy_candidates: tuple[StrategyCandidate, ...],
    dataset_content_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> CandidatePreflightReport:
    if tuple(fold.fold_id for fold in folds) != ("F1", "F2", "F3", "F4"):
        raise ValueError("Preflight requires the four frozen Walk-forward Folds")
    if _SHA256.fullmatch(dataset_content_hash) is None:
        raise ValueError("dataset_content_hash must be a lowercase SHA-256")
    if _SHA256.fullmatch(dependency_lock_hash) is None:
        raise ValueError("dependency_lock_hash must be a lowercase SHA-256")
    if _COMMIT.fullmatch(code_commit) is None:
        raise ValueError("code_commit must be a hexadecimal commit identity")
    candidates = _ordered(strategy_candidates)
    if not candidates or len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("Candidate input must be nonempty with unique identities")
    if any(
        candidate.decision_time_utc_ms < folds[0].training_start_utc_ms
        or candidate.decision_time_utc_ms > folds[-1].validation_end_utc_ms
        for candidate in candidates
    ):
        raise ValueError("Candidate is outside V2-A development boundary")

    fold_inputs = tuple(
        FoldCandidateInputs(
            fold.fold_id,
            tuple(
                candidate
                for candidate in candidates
                if fold.training_start_utc_ms
                <= candidate.decision_time_utc_ms
                <= fold.training_end_utc_ms
            ),
            tuple(
                candidate
                for candidate in candidates
                if fold.validation_start_utc_ms
                <= candidate.decision_time_utc_ms
                <= fold.validation_end_utc_ms
            ),
        )
        for fold in folds
    )
    return run_fold_candidate_preflight(
        folds=folds,
        fold_candidate_inputs=fold_inputs,
        dataset_content_hash=dataset_content_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )


def _source_split_name(fold_id: str) -> str:
    return "TRAINING" if fold_id in {"F1", "F2"} else "VALIDATION"


def load_fold_candidate_inputs(
    *,
    root: Path,
    folds: tuple[WalkForwardFold, ...],
    code_commit: str,
    dependency_lock_hash: str,
) -> tuple[FoldCandidateInputs, ...]:
    inputs = []
    for fold in folds:
        training, _, _, _ = _load_candidates(
            root,
            Split(
                _source_split_name(fold.fold_id),
                fold.training_start_utc_ms,
                fold.training_end_utc_ms,
            ),
            "NATIVE_PRIMARY",
            fold.training_start_utc_ms,
            code_commit,
            dependency_lock_hash,
        )
        validation, _, _, _ = _load_candidates(
            root,
            Split(
                _source_split_name(fold.fold_id),
                fold.validation_start_utc_ms,
                fold.validation_end_utc_ms,
            ),
            "NATIVE_PRIMARY",
            fold.training_start_utc_ms,
            code_commit,
            dependency_lock_hash,
        )
        inputs.append(
            FoldCandidateInputs(
                fold.fold_id,
                tuple(training),
                tuple(validation),
            )
        )
    return tuple(inputs)


def prepare_candidate_preflight(*, root: Path, code_commit: str) -> CandidatePreflightBundle:
    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    dataset_content_hash = approval.manifest["hybrid_historical_data_bundle_hash"]
    dependency_lock_hash = approval.manifest["dependency_lock_hash"]
    fold_inputs = load_fold_candidate_inputs(
        root=root,
        folds=WALK_FORWARD_FOLDS,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    report = run_fold_candidate_preflight(
        folds=WALK_FORWARD_FOLDS,
        fold_candidate_inputs=fold_inputs,
        dataset_content_hash=dataset_content_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    manifests = tuple(
        build_threshold_manifest(
            fold=fold,
            training_candidates=inputs.training_candidates,
            dataset_content_hash=dataset_content_hash,
            candidate_filter_version=CANDIDATE_FILTER_VERSION,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
        for fold, inputs in zip(WALK_FORWARD_FOLDS, fold_inputs, strict=True)
    )
    identity = build_experiment_identity(
        strategy_identities=(
            StrategyIdentity.V1_BASELINE,
            StrategyIdentity.V2A_Q50,
            StrategyIdentity.V2A_Q67,
        ),
        fold_manifest_hashes=tuple(canonical_sha256(fold) for fold in WALK_FORWARD_FOLDS),
        threshold_manifests=manifests,
        dataset_content_hash=dataset_content_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
        candidate_filter_version=CANDIDATE_FILTER_VERSION,
    )
    return CandidatePreflightBundle(report, identity, fold_inputs)
