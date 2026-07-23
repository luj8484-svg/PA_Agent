from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.approval import verify_data_approval_manifest
from pa_agent.research_2d.runner import (
    Scenario,
    Split,
    _load_candidates,
    _market_evidence,
    _run_scenario,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_v2a.domain import StrategyIdentity, WalkForwardFold
from pa_agent.research_v2a.identity import ExperimentIdentity
from pa_agent.research_v2a.preflight import (
    PREFLIGHT_FAILED,
    CandidatePreflightReport,
    CandidatePreflightStrategyResult,
    FoldPreflightResult,
)


@dataclass(frozen=True, slots=True)
class WalkForwardTask:
    key: str
    fold: WalkForwardFold
    strategy_identity: StrategyIdentity
    authority: str
    scenario: Scenario
    initial_capital: Decimal
    accepted_candidate_ids: tuple[str, ...]
    accepted_candidate_content_hash: str


@dataclass(frozen=True, slots=True)
class WalkForwardTaskResult:
    key: str
    fold_id: str
    strategy_identity: StrategyIdentity
    runs: tuple[object, ...]
    metrics: tuple[dict[str, object], ...]


def _strategy_result(
    fold: FoldPreflightResult,
    strategy: StrategyIdentity,
) -> CandidatePreflightStrategyResult:
    if strategy is StrategyIdentity.V1_BASELINE:
        return fold.baseline
    if strategy is StrategyIdentity.V2A_Q50:
        return fold.q50
    if strategy is StrategyIdentity.V2A_Q67:
        return fold.q67
    raise ValueError("unsupported strategy identity")


def build_walk_forward_tasks(
    *,
    preflight: CandidatePreflightReport,
    folds: tuple[WalkForwardFold, ...],
    baseline_scenario: Scenario,
) -> tuple[WalkForwardTask, ...]:
    if baseline_scenario != Scenario("BASE_1X", Decimal("1"), Decimal("1")):
        raise ValueError("Walk-forward only supports BASE_1X")
    if tuple(fold.fold_id for fold in folds) != ("F1", "F2", "F3", "F4"):
        raise ValueError("Walk-forward requires the four frozen Folds")
    if preflight.status == PREFLIGHT_FAILED:
        if preflight.eligible_strategies or preflight.eligible_task_count != 0:
            raise ValueError("failed Preflight cannot register tasks")
        return ()
    expected_count = 4 * len(preflight.eligible_strategies)
    if expected_count not in {8, 12} or preflight.eligible_task_count != expected_count:
        raise ValueError("Preflight task eligibility must be exactly 8 or 12")
    if preflight.eligible_strategies[0] is not StrategyIdentity.V1_BASELINE:
        raise ValueError("eligible strategies must begin with V1_BASELINE")
    fold_results = {item.fold_id: item for item in preflight.fold_results}
    if set(fold_results) != {"F1", "F2", "F3", "F4"}:
        raise ValueError("Preflight Fold results are incomplete")

    tasks = []
    for fold in folds:
        result = fold_results[fold.fold_id]
        for strategy in preflight.eligible_strategies:
            strategy_result = _strategy_result(result, strategy)
            tasks.append(
                WalkForwardTask(
                    key=f"{fold.fold_id}:{strategy.value}:NATIVE_PRIMARY:BASE_1X",
                    fold=fold,
                    strategy_identity=strategy,
                    authority="NATIVE_PRIMARY",
                    scenario=baseline_scenario,
                    initial_capital=Decimal("10000"),
                    accepted_candidate_ids=strategy_result.accepted_candidate_ids,
                    accepted_candidate_content_hash=(
                        strategy_result.accepted_candidate_content_hash
                    ),
                )
            )
    return tuple(tasks)


def _gap_source_split_name(fold_id: str) -> str:
    if fold_id in {"F1", "F2"}:
        return "TRAINING"
    if fold_id in {"F3", "F4"}:
        return "VALIDATION"
    raise ValueError("unsupported Fold identity")


def run_walk_forward_task(
    task: WalkForwardTask,
    *,
    root: Path,
    experiment_identity: ExperimentIdentity,
) -> WalkForwardTaskResult:
    if task.initial_capital != Decimal("10000"):
        raise ValueError("each Fold must start with exactly 10000 USDT")
    if task.strategy_identity not in experiment_identity.strategy_identities:
        raise ValueError("task strategy is absent from experiment identity")
    if task.authority != "NATIVE_PRIMARY" or task.scenario.name != "BASE_1X":
        raise ValueError("Walk-forward execution is restricted to Native BASE_1X")

    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    split = Split(
        _gap_source_split_name(task.fold.fold_id),
        task.fold.validation_start_utc_ms,
        task.fold.validation_end_utc_ms,
    )
    candidates, trends, _, _ = _load_candidates(
        root,
        split,
        task.authority,
        task.fold.training_start_utc_ms,
        experiment_identity.code_commit,
        experiment_identity.dependency_lock_hash,
    )
    accepted_ids = set(task.accepted_candidate_ids)
    filtered = tuple(
        candidate for candidate in candidates if candidate.candidate_id in accepted_ids
    )
    if len(filtered) != len(accepted_ids):
        raise ValueError("Preflight accepted Candidate identities are unavailable")
    if canonical_sha256(filtered) != task.accepted_candidate_content_hash:
        raise ValueError("Preflight accepted Candidate hash mismatch")
    evidence_data = _market_evidence(root, split, filtered, trends)
    runs, metrics = _run_scenario(
        root=root,
        split=split,
        authority=task.authority,
        scenario=task.scenario,
        candidates=filtered,
        trends=trends,
        evidence_data=evidence_data,
        experiment_id=experiment_identity.computational_experiment_id,
        approval_hash=approval.manifest_hash,
        code_commit=experiment_identity.code_commit,
        dependency_lock_hash=experiment_identity.dependency_lock_hash,
    )
    return WalkForwardTaskResult(
        key=task.key,
        fold_id=task.fold.fold_id,
        strategy_identity=task.strategy_identity,
        runs=tuple(runs),
        metrics=tuple(metrics),
    )
