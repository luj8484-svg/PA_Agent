from __future__ import annotations

import os
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.approval import verify_data_approval_manifest
from pa_agent.research_2d.parallel import (
    WatchdogConfig,
    current_rss_bytes,
    exclusive_output_lock,
    peak_rss_bytes,
    physical_memory_status,
    pickle_size,
    run_tasks,
)
from pa_agent.research_2d.runner import (
    Scenario,
    Split,
    _load_candidates,
    _market_evidence,
    _run_scenario,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.rejections import ExecutionRejection
from pa_agent.research_backtest.simulation.domain import PathState
from pa_agent.research_backtest.versions import MAX_HOLD_VERSION
from pa_agent.research_v2a.domain import (
    WALK_FORWARD_FOLDS,
    StrategyIdentity,
    WalkForwardFold,
)
from pa_agent.research_v2a.execution_horizon import (
    EXECUTION_HORIZON_GATE_VERSION,
    FROZEN_MAXIMUM_HOLDING_MINUTES,
)
from pa_agent.research_v2a.identity import (
    ExperimentIdentity,
    verify_experiment_code_identity,
)
from pa_agent.research_v2a.preflight import (
    PREFLIGHT_FAILED,
    PREFLIGHT_SCHEMA_VERSION,
    CandidatePreflightReport,
    CandidatePreflightStrategyResult,
    FoldPreflightResult,
    prepare_candidate_preflight,
)
from pa_agent.research_v2a.reporting import publish_walk_forward_report

_SHA256 = re.compile(r"[0-9a-f]{64}")


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
    experiment_identity: ExperimentIdentity | None = None


@dataclass(frozen=True, slots=True)
class WalkForwardTaskResult:
    key: str
    fold_id: str
    strategy_identity: StrategyIdentity
    runs: tuple[object, ...]
    metrics: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class WalkForwardWorkerPayload:
    key: str
    task: WalkForwardTask
    root: Path


@dataclass(frozen=True, slots=True)
class WalkForwardWorkerResult:
    key: str
    task_result: WalkForwardTaskResult
    payload_pickle_bytes: int
    result_pickle_bytes: int
    worker_pid: int
    worker_peak_rss_bytes: int


@dataclass(frozen=True, slots=True)
class CapacityProbeReport:
    task_key: str
    elapsed_seconds: Decimal
    cpu_seconds: Decimal
    parent_peak_rss_bytes: int
    worker_peak_rss_bytes: int
    payload_pickle_bytes: int
    result_pickle_bytes: int
    output_size_bytes: int
    hard_timeout_seconds: Decimal
    no_progress_timeout_seconds: None


@dataclass(frozen=True, slots=True)
class FoldPerformance:
    fold_id: str
    net_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    max_drawdown: Decimal
    trade_count: int
    symbol_net_pnl: tuple[tuple[str, Decimal], ...]
    symbol_trade_counts: tuple[tuple[str, int], ...]
    side_net_pnl: tuple[tuple[str, Decimal], ...]
    side_trade_counts: tuple[tuple[str, int], ...]
    reached_fold_end: bool
    halted: bool
    data_invalid: bool
    invariant_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.fold_id not in {"F1", "F2", "F3", "F4"}:
            raise ValueError("unsupported Fold identity")
        if self.gross_profit < 0 or self.gross_loss > 0:
            raise ValueError("gross profit/loss signs are invalid")
        if self.trade_count < 0:
            raise ValueError("trade_count cannot be negative")
        if self.max_drawdown < 0:
            raise ValueError("max_drawdown cannot be negative")


@dataclass(frozen=True, slots=True)
class AggregatePerformance:
    fold_results: tuple[FoldPerformance, ...]
    total_net_pnl: Decimal
    aggregate_return: Decimal
    total_gross_profit: Decimal
    total_gross_loss: Decimal
    aggregate_profit_factor: Decimal | None
    total_trade_count: int
    median_fold_net_pnl: Decimal
    median_fold_max_drawdown: Decimal
    symbol_net_pnl: tuple[tuple[str, Decimal], ...]
    symbol_trade_counts: tuple[tuple[str, int], ...]
    side_net_pnl: tuple[tuple[str, Decimal], ...]
    side_trade_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class PromotionCriterion:
    name: str
    passed: bool


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    candidate: StrategyIdentity
    aggregate: AggregatePerformance
    passed: bool
    criteria: tuple[PromotionCriterion, ...]
    failure_reasons: tuple[str, ...]
    baseline_path_decision: PromotionDecision | None = None
    conservative_path_decision: PromotionDecision | None = None


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    selected: StrategyIdentity | None
    conclusion: str


V2A_WALK_FORWARD_PASSED = "V2A_WALK_FORWARD_PASSED"
V2A_WALK_FORWARD_FAILED = "V2A_WALK_FORWARD_FAILED"


def _decimal_median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("median requires values")
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _sum_breakdown(
    fold_results: tuple[FoldPerformance, ...],
    value_field: str,
    count_field: str,
    required_keys: tuple[str, str],
) -> tuple[tuple[tuple[str, Decimal], ...], tuple[tuple[str, int], ...]]:
    values = {key: Decimal("0") for key in required_keys}
    counts = {key: 0 for key in required_keys}
    for fold in fold_results:
        fold_values = dict(getattr(fold, value_field))
        fold_counts = dict(getattr(fold, count_field))
        if set(fold_values) != set(required_keys) or set(fold_counts) != set(required_keys):
            raise ValueError("Fold performance breakdown keys are incomplete")
        for key in required_keys:
            values[key] += fold_values[key]
            counts[key] += fold_counts[key]
    return tuple(values.items()), tuple(counts.items())


def aggregate_fold_performance(
    fold_results: tuple[FoldPerformance, ...], *, initial_capital_per_fold: Decimal
) -> AggregatePerformance:
    if initial_capital_per_fold != Decimal("10000"):
        raise ValueError("each Fold must independently start with 10000 USDT")
    if tuple(item.fold_id for item in fold_results) != ("F1", "F2", "F3", "F4"):
        raise ValueError("aggregation requires exactly F1, F2, F3 and F4")
    total_net_pnl = sum((item.net_pnl for item in fold_results), Decimal("0"))
    total_gross_profit = sum((item.gross_profit for item in fold_results), Decimal("0"))
    total_gross_loss = sum((item.gross_loss for item in fold_results), Decimal("0"))
    symbol_values, symbol_counts = _sum_breakdown(
        fold_results,
        "symbol_net_pnl",
        "symbol_trade_counts",
        ("BTCUSDT", "ETHUSDT"),
    )
    side_values, side_counts = _sum_breakdown(
        fold_results,
        "side_net_pnl",
        "side_trade_counts",
        ("LONG", "SHORT"),
    )
    return AggregatePerformance(
        fold_results=fold_results,
        total_net_pnl=total_net_pnl,
        aggregate_return=total_net_pnl / Decimal("40000"),
        total_gross_profit=total_gross_profit,
        total_gross_loss=total_gross_loss,
        aggregate_profit_factor=(
            total_gross_profit / abs(total_gross_loss) if total_gross_loss else None
        ),
        total_trade_count=sum(item.trade_count for item in fold_results),
        median_fold_net_pnl=_decimal_median(tuple(item.net_pnl for item in fold_results)),
        median_fold_max_drawdown=_decimal_median(tuple(item.max_drawdown for item in fold_results)),
        symbol_net_pnl=symbol_values,
        symbol_trade_counts=symbol_counts,
        side_net_pnl=side_values,
        side_trade_counts=side_counts,
    )


def _profit_concentration_passes(aggregate: AggregatePerformance) -> bool:
    positives = tuple(item.net_pnl for item in aggregate.fold_results if item.net_pnl > 0)
    return bool(positives) and max(positives) <= sum(positives) * Decimal("0.60")


def _diversification_passes(
    values: tuple[tuple[str, Decimal], ...],
    counts: tuple[tuple[str, int], ...],
) -> bool:
    return all(value > 0 for _, value in values) and all(count > 0 for _, count in counts)


def evaluate_promotion(
    *,
    candidate: StrategyIdentity,
    aggregate: AggregatePerformance,
    baseline: AggregatePerformance,
) -> PromotionDecision:
    if candidate not in {StrategyIdentity.V2A_Q50, StrategyIdentity.V2A_Q67}:
        raise ValueError("only V2-A candidates may be evaluated for promotion")
    candidate_by_fold = {item.fold_id: item for item in aggregate.fold_results}
    baseline_by_fold = {item.fold_id: item for item in baseline.fold_results}
    if candidate_by_fold.keys() != baseline_by_fold.keys():
        raise ValueError("candidate and baseline Fold identities differ")
    pf_passes = (
        aggregate.aggregate_profit_factor is not None
        and aggregate.aggregate_profit_factor >= Decimal("1.10")
    ) or (
        aggregate.aggregate_profit_factor is None
        and aggregate.total_gross_profit > 0
        and aggregate.total_gross_loss == 0
    )
    criteria = (
        PromotionCriterion(
            "POSITIVE_FOLD_COUNT",
            sum(item.net_pnl > 0 for item in aggregate.fold_results) >= 3,
        ),
        PromotionCriterion(
            "OUTPERFORM_BASELINE_FOLD_COUNT",
            sum(
                candidate_by_fold[key].net_pnl > baseline_by_fold[key].net_pnl
                for key in candidate_by_fold
            )
            >= 3,
        ),
        PromotionCriterion("TOTAL_NET_PNL", aggregate.total_net_pnl > 0),
        PromotionCriterion("PROFIT_FACTOR", pf_passes),
        PromotionCriterion("TOTAL_TRADE_COUNT", aggregate.total_trade_count >= 60),
        PromotionCriterion(
            "MIN_FOLD_TRADE_COUNT",
            all(item.trade_count >= 10 for item in aggregate.fold_results),
        ),
        PromotionCriterion("MEDIAN_FOLD_NET_PNL", aggregate.median_fold_net_pnl > 0),
        PromotionCriterion(
            "MEDIAN_DRAWDOWN",
            aggregate.median_fold_max_drawdown <= baseline.median_fold_max_drawdown,
        ),
        PromotionCriterion("FOLD_PROFIT_CONCENTRATION", _profit_concentration_passes(aggregate)),
        PromotionCriterion(
            "SYMBOL_DIVERSIFICATION",
            _diversification_passes(aggregate.symbol_net_pnl, aggregate.symbol_trade_counts),
        ),
        PromotionCriterion(
            "SIDE_DIVERSIFICATION",
            _diversification_passes(aggregate.side_net_pnl, aggregate.side_trade_counts),
        ),
        PromotionCriterion(
            "COMPLETE_VALID_PATHS",
            all(
                item.reached_fold_end and not item.halted and not item.data_invalid
                for item in aggregate.fold_results
            ),
        ),
        PromotionCriterion(
            "INVARIANTS",
            all(not item.invariant_failures for item in aggregate.fold_results),
        ),
    )
    failures = tuple(item.name for item in criteria if not item.passed)
    return PromotionDecision(
        candidate=candidate,
        aggregate=aggregate,
        passed=not failures,
        criteria=criteria,
        failure_reasons=failures,
    )


def evaluate_dual_path_promotion(
    *,
    candidate: StrategyIdentity,
    baseline_path_aggregate: AggregatePerformance,
    conservative_path_aggregate: AggregatePerformance,
    baseline_reference_by_path: tuple[AggregatePerformance, AggregatePerformance],
) -> PromotionDecision:
    baseline_reference, conservative_reference = baseline_reference_by_path
    baseline_decision = evaluate_promotion(
        candidate=candidate,
        aggregate=baseline_path_aggregate,
        baseline=baseline_reference,
    )
    conservative_decision = evaluate_promotion(
        candidate=candidate,
        aggregate=conservative_path_aggregate,
        baseline=conservative_reference,
    )
    failures = (
        *(f"BASELINE:{reason}" for reason in baseline_decision.failure_reasons),
        *(f"CONSERVATIVE:{reason}" for reason in conservative_decision.failure_reasons),
    )
    criteria = (
        *(
            PromotionCriterion(f"BASELINE:{item.name}", item.passed)
            for item in baseline_decision.criteria
        ),
        *(
            PromotionCriterion(f"CONSERVATIVE:{item.name}", item.passed)
            for item in conservative_decision.criteria
        ),
    )
    return PromotionDecision(
        candidate=candidate,
        aggregate=conservative_path_aggregate,
        passed=baseline_decision.passed and conservative_decision.passed,
        criteria=criteria,
        failure_reasons=failures,
        baseline_path_decision=baseline_decision,
        conservative_path_decision=conservative_decision,
    )


def _selection_positive_fold_count(decision: PromotionDecision) -> int:
    aggregates = (
        (decision.baseline_path_decision.aggregate, decision.conservative_path_decision.aggregate)
        if decision.baseline_path_decision is not None
        and decision.conservative_path_decision is not None
        else (decision.aggregate,)
    )
    return min(sum(item.net_pnl > 0 for item in aggregate.fold_results) for aggregate in aggregates)


def _selection_max_drawdown(decision: PromotionDecision) -> Decimal:
    aggregates = (
        (decision.baseline_path_decision.aggregate, decision.conservative_path_decision.aggregate)
        if decision.baseline_path_decision is not None
        and decision.conservative_path_decision is not None
        else (decision.aggregate,)
    )
    return max(aggregate.median_fold_max_drawdown for aggregate in aggregates)


def select_walk_forward_candidate(
    *, q50: PromotionDecision, q67: PromotionDecision
) -> SelectionDecision:
    if q50.candidate is not StrategyIdentity.V2A_Q50:
        raise ValueError("q50 decision identity mismatch")
    if q67.candidate is not StrategyIdentity.V2A_Q67:
        raise ValueError("q67 decision identity mismatch")
    if not q50.passed and not q67.passed:
        return SelectionDecision(None, V2A_WALK_FORWARD_FAILED)
    if q50.passed and not q67.passed:
        return SelectionDecision(StrategyIdentity.V2A_Q50, V2A_WALK_FORWARD_PASSED)
    if q67.passed and not q50.passed:
        return SelectionDecision(StrategyIdentity.V2A_Q67, V2A_WALK_FORWARD_PASSED)
    q50_pf = q50.aggregate.aggregate_profit_factor
    q67_pf = q67.aggregate.aggregate_profit_factor
    q67_is_strictly_superior = (
        q50_pf is not None
        and q67_pf is not None
        and q67_pf >= q50_pf + Decimal("0.10")
        and q67.aggregate.total_net_pnl >= q50.aggregate.total_net_pnl * Decimal("1.25")
        and q67.aggregate.total_trade_count >= 60
        and _selection_positive_fold_count(q67) >= _selection_positive_fold_count(q50)
        and _selection_max_drawdown(q67) <= _selection_max_drawdown(q50)
    )
    selected = StrategyIdentity.V2A_Q67 if q67_is_strictly_superior else StrategyIdentity.V2A_Q50
    return SelectionDecision(selected, V2A_WALK_FORWARD_PASSED)


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


def _validate_preflight_horizon_contract(preflight: CandidatePreflightReport) -> None:
    if preflight.schema_version != PREFLIGHT_SCHEMA_VERSION:
        raise ValueError("Preflight schema does not include the frozen Execution Horizon Gate")
    frozen_config_hash = execution_time_config(
        entry_delay_minutes=1,
        exit_delay_minutes=1,
    ).config_content_hash
    if (
        preflight.execution_horizon_gate_version != EXECUTION_HORIZON_GATE_VERSION
        or preflight.execution_time_config_content_hash != frozen_config_hash
        or preflight.maximum_holding_minutes != FROZEN_MAXIMUM_HOLDING_MINUTES
        or preflight.max_hold_version != MAX_HOLD_VERSION
    ):
        raise ValueError("Execution Horizon policy identity mismatch")
    for fold in preflight.fold_results:
        if _SHA256.fullmatch(fold.execution_horizon_decision_content_hash) is None:
            raise ValueError("Execution Horizon decision hash is invalid")
        rejected = fold.execution_horizon_rejected_candidate_ids
        if (
            fold.raw_validation_candidate_count
            != fold.validation_candidate_count + fold.execution_horizon_rejected_count
            or fold.execution_horizon_rejected_count != len(rejected)
            or len(set(rejected)) != len(rejected)
        ):
            raise ValueError("Execution Horizon Candidate counts are inconsistent")
        baseline_ids = fold.baseline.accepted_candidate_ids
        if (
            fold.baseline.validation_candidate_count != fold.validation_candidate_count
            or fold.baseline.accepted_candidate_count != fold.validation_candidate_count
            or fold.baseline.rejected_candidate_count != 0
            or len(baseline_ids) != fold.baseline.accepted_candidate_count
            or len(set(baseline_ids)) != len(baseline_ids)
            or set(rejected).intersection(baseline_ids)
        ):
            raise ValueError("Execution Horizon baseline accepted set is inconsistent")
        baseline_set = set(baseline_ids)
        for strategy_result in (fold.q50, fold.q67):
            accepted_ids = strategy_result.accepted_candidate_ids
            if (
                strategy_result.validation_candidate_count != fold.validation_candidate_count
                or strategy_result.accepted_candidate_count != len(accepted_ids)
                or strategy_result.rejected_candidate_count
                != fold.validation_candidate_count - len(accepted_ids)
                or len(set(accepted_ids)) != len(accepted_ids)
                or not set(accepted_ids).issubset(baseline_set)
                or set(rejected).intersection(accepted_ids)
            ):
                raise ValueError("Execution Horizon filtered accepted set is inconsistent")


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
    _validate_preflight_horizon_contract(preflight)
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


def execute_walk_forward_task(
    payload: WalkForwardWorkerPayload,
    progress_queue=None,
    watchdog_config: WatchdogConfig | None = None,
) -> WalkForwardWorkerResult:
    if watchdog_config is None:
        raise ValueError("worker watchdog config is required")
    if watchdog_config.no_progress_timeout_seconds is not None:
        raise ValueError("V2-A no-progress watchdog must remain disabled")
    identity = payload.task.experiment_identity
    if identity is None:
        raise ValueError("V2-A task is missing its experiment identity")
    print(
        f"worker_start task_key={payload.key} "
        f"hard_timeout_seconds={watchdog_config.hard_timeout_seconds} "
        "no_progress_timeout_seconds=None",
        flush=True,
    )
    if progress_queue is not None:
        progress_queue.put((payload.key, "STARTED", 0, None, os.getpid(), current_rss_bytes()))
    task_result = run_walk_forward_task(
        payload.task,
        root=payload.root,
        experiment_identity=identity,
    )
    result = WalkForwardWorkerResult(
        key=payload.key,
        task_result=task_result,
        payload_pickle_bytes=pickle_size(payload),
        result_pickle_bytes=0,
        worker_pid=os.getpid(),
        worker_peak_rss_bytes=peak_rss_bytes(),
    )
    result = replace(result, result_pickle_bytes=pickle_size(result))
    if progress_queue is not None:
        progress_queue.put((payload.key, "COMPLETED", 0, None, os.getpid(), current_rss_bytes()))
    return result


def run_capacity_probe(
    *,
    task: WalkForwardTask,
    root: Path,
    diagnostics_output: Path,
    hard_timeout_seconds: float = 21_600,
    no_progress_timeout_seconds: None = None,
) -> CapacityProbeReport:
    if task.key != "F4:V1_BASELINE:NATIVE_PRIMARY:BASE_1X":
        raise ValueError("capacity probe must run only F4 V1_BASELINE")
    if task.fold.fold_id != "F4" or task.strategy_identity is not StrategyIdentity.V1_BASELINE:
        raise ValueError("capacity probe task identity must be F4 V1_BASELINE")
    if no_progress_timeout_seconds is not None:
        raise ValueError("V2-A no-progress watchdog is permanently disabled")
    if hard_timeout_seconds != 21_600:
        raise ValueError("V2-A hard timeout is frozen at 21600 seconds")
    if task.experiment_identity is None:
        raise ValueError("capacity probe task requires experiment identity")
    payload = WalkForwardWorkerPayload(task.key, task, root)
    started = time.perf_counter()
    cpu_started = time.process_time()
    batch = run_tasks(
        (payload,),
        max_workers=1,
        hard_timeout_seconds=hard_timeout_seconds,
        no_progress_timeout_seconds=None,
        worker=execute_walk_forward_task,
    )
    elapsed = Decimal(str(time.perf_counter() - started))
    cpu = Decimal(str(time.process_time() - cpu_started))
    result = batch.results[0]
    report = CapacityProbeReport(
        task_key=task.key,
        elapsed_seconds=elapsed,
        cpu_seconds=cpu,
        parent_peak_rss_bytes=batch.parent_peak_rss_bytes,
        worker_peak_rss_bytes=result.worker_peak_rss_bytes,
        payload_pickle_bytes=pickle_size(payload),
        result_pickle_bytes=result.result_pickle_bytes,
        output_size_bytes=result.result_pickle_bytes,
        hard_timeout_seconds=Decimal(str(hard_timeout_seconds)),
        no_progress_timeout_seconds=None,
    )
    diagnostics_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = diagnostics_output.with_suffix(diagnostics_output.suffix + ".tmp")
    from pa_agent.research_backtest.domain.canonical import canonical_dumps

    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_dumps(report) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, diagnostics_output)
    return report


def run_v2a_candidate_preflight(*, root: Path, output_root: Path, code_commit: str) -> Path:
    verify_experiment_code_identity(
        repository_root=Path(__file__).resolve().parents[2],
        code_commit=code_commit,
    )
    bundle = prepare_candidate_preflight(root=root, code_commit=code_commit)
    with exclusive_output_lock(output_root.parent):
        published = publish_walk_forward_report(
            output_dir=output_root,
            canonical_economics={
                "preflight": bundle.report,
                "experiment_identity": bundle.experiment_identity,
            },
            diagnostics={"minute_replay_performed": False},
        )
    return published.output_dir


def _path_value(value: object) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def validate_walk_forward_task_result(result: WalkForwardTaskResult) -> None:
    if len(result.runs) != 2 or len(result.metrics) != 2:
        raise ValueError(f"{result.key}: both ambiguity paths are required")
    run_by_path = {run.path_kind.value: run for run in result.runs}
    metric_by_path = {str(metric["path_kind"]): metric for metric in result.metrics}
    required_paths = {"BASELINE", "CONSERVATIVE"}
    if set(run_by_path) != required_paths or set(metric_by_path) != required_paths:
        raise ValueError(f"{result.key}: ambiguity path set is incomplete")
    for path_kind in ("BASELINE", "CONSERVATIVE"):
        run = run_by_path[path_kind]
        metric = metric_by_path[path_kind]
        data_invalid = any(
            isinstance(item, ExecutionRejection) and item.reason.value == "DATA_INVALID"
            for item in run.planning_outputs
        )
        if data_invalid:
            raise ValueError(f"{result.key}:{path_kind}:DATA_INVALID planning rejection")
        state = _path_value(run.path_result.path_state)
        if state != PathState.VALID.value:
            raise ValueError(
                f"{result.key}:{path_kind}:{state}:"
                f"{run.path_result.invalid_reason or 'PATH_NOT_VALID'}"
            )
        if run.path_result.invalid_reason is not None:
            raise ValueError(f"{result.key}:{path_kind}:INVALID_REASON_PRESENT")
        expected_end = int(metric["split_end_utc_ms"]) + 1
        if run.path_result.final_processed_time_utc_ms != expected_end:
            raise ValueError(f"{result.key}:{path_kind}:SPLIT_NOT_COMPLETED")


def _fold_performance(
    result: WalkForwardTaskResult,
    *,
    path_kind: str,
) -> FoldPerformance:
    validate_walk_forward_task_result(result)
    run_by_path = {run.path_kind.value: run for run in result.runs}
    metric_by_path = {str(metric["path_kind"]): metric for metric in result.metrics}
    selected = run_by_path[path_kind]
    metric = metric_by_path[path_kind]
    trades = tuple(selected.trades)
    symbol_pnl = Counter()
    symbol_counts = Counter()
    side_pnl = Counter()
    side_counts = Counter()
    for trade in trades:
        symbol_pnl[trade.symbol] += trade.net_pnl
        symbol_counts[trade.symbol] += 1
        side_pnl[trade.side.value] += trade.net_pnl
        side_counts[trade.side.value] += 1
    return FoldPerformance(
        fold_id=result.fold_id,
        net_pnl=sum((trade.net_pnl for trade in trades), Decimal("0")),
        gross_profit=sum((trade.net_pnl for trade in trades if trade.net_pnl > 0), Decimal("0")),
        gross_loss=sum((trade.net_pnl for trade in trades if trade.net_pnl < 0), Decimal("0")),
        max_drawdown=Decimal(str(metric["engine_peak_observed_drawdown"])),
        trade_count=len(trades),
        symbol_net_pnl=tuple((symbol, symbol_pnl[symbol]) for symbol in ("BTCUSDT", "ETHUSDT")),
        symbol_trade_counts=tuple(
            (symbol, symbol_counts[symbol]) for symbol in ("BTCUSDT", "ETHUSDT")
        ),
        side_net_pnl=tuple((side, side_pnl[side]) for side in ("LONG", "SHORT")),
        side_trade_counts=tuple((side, side_counts[side]) for side in ("LONG", "SHORT")),
        reached_fold_end=True,
        halted=False,
        data_invalid=False,
        invariant_failures=(),
    )


def _aggregate_strategy_results(
    results: tuple[WalkForwardWorkerResult, ...],
    strategy: StrategyIdentity,
    *,
    path_kind: str,
) -> AggregatePerformance:
    by_fold = {
        result.task_result.fold_id: _fold_performance(
            result.task_result,
            path_kind=path_kind,
        )
        for result in results
        if result.task_result.strategy_identity is strategy
    }
    if set(by_fold) != {"F1", "F2", "F3", "F4"}:
        raise ValueError(f"{strategy.value}: Fold result set is incomplete")
    return aggregate_fold_performance(
        tuple(by_fold[name] for name in ("F1", "F2", "F3", "F4")),
        initial_capital_per_fold=Decimal("10000"),
    )


def validate_walk_forward_worker_result(result: WalkForwardWorkerResult) -> None:
    validate_walk_forward_task_result(result.task_result)


def _select_worker_count(*, requested: int, probe: CapacityProbeReport) -> int:
    if requested not in {2, 6}:
        raise ValueError("V2-A formal max_workers must be 2 or 6")
    if requested == 2:
        return 2
    _, available = physical_memory_status()
    six_worker_budget = (
        6 * probe.worker_peak_rss_bytes * Decimal("1.5") + probe.parent_peak_rss_bytes
    )
    return 6 if six_worker_budget <= Decimal(available) * Decimal("0.5") else 2


def run_v2a_walk_forward(
    *,
    root: Path,
    output_root: Path,
    code_commit: str,
    max_workers: int,
    hard_timeout_seconds: float = 21_600,
    no_progress_timeout_seconds: None = None,
) -> Path:
    verify_experiment_code_identity(
        repository_root=Path(__file__).resolve().parents[2],
        code_commit=code_commit,
    )
    if no_progress_timeout_seconds is not None:
        raise ValueError("V2-A no-progress watchdog is permanently disabled")
    if hard_timeout_seconds != 21_600:
        raise ValueError("V2-A hard timeout is frozen at 21600 seconds")
    if max_workers not in {2, 6}:
        raise ValueError("V2-A max_workers must be 2 or 6")
    with exclusive_output_lock(output_root):
        bundle = prepare_candidate_preflight(root=root, code_commit=code_commit)
        preflight_dir = output_root / "preflight"
        publish_walk_forward_report(
            output_dir=preflight_dir,
            canonical_economics={
                "preflight": bundle.report,
                "experiment_identity": bundle.experiment_identity,
            },
            diagnostics={"minute_replay_performed": False},
        )
        if bundle.report.status == PREFLIGHT_FAILED:
            return preflight_dir
        tasks = tuple(
            replace(task, experiment_identity=bundle.experiment_identity)
            for task in build_walk_forward_tasks(
                preflight=bundle.report,
                folds=WALK_FORWARD_FOLDS,
                baseline_scenario=Scenario("BASE_1X", Decimal("1"), Decimal("1")),
            )
        )
        probe_task = next(
            task for task in tasks if task.key == "F4:V1_BASELINE:NATIVE_PRIMARY:BASE_1X"
        )
        probe = run_capacity_probe(
            task=probe_task,
            root=root,
            diagnostics_output=output_root / "diagnostics" / "capacity_probe.json",
            hard_timeout_seconds=hard_timeout_seconds,
            no_progress_timeout_seconds=None,
        )
        effective_workers = _select_worker_count(requested=max_workers, probe=probe)
        payloads = tuple(WalkForwardWorkerPayload(task.key, task, root) for task in tasks)
        batch = run_tasks(
            payloads,
            max_workers=effective_workers,
            hard_timeout_seconds=hard_timeout_seconds,
            no_progress_timeout_seconds=None,
            worker=execute_walk_forward_task,
            result_validator=validate_walk_forward_worker_result,
        )
        results = tuple(batch.results)
        baseline_by_path = {
            path_kind: _aggregate_strategy_results(
                results,
                StrategyIdentity.V1_BASELINE,
                path_kind=path_kind,
            )
            for path_kind in ("BASELINE", "CONSERVATIVE")
        }
        decisions = {}
        for strategy in bundle.report.eligible_strategies:
            if strategy is StrategyIdentity.V1_BASELINE:
                continue
            candidate_by_path = {
                path_kind: _aggregate_strategy_results(
                    results,
                    strategy,
                    path_kind=path_kind,
                )
                for path_kind in ("BASELINE", "CONSERVATIVE")
            }
            decisions[strategy] = evaluate_dual_path_promotion(
                candidate=strategy,
                baseline_path_aggregate=candidate_by_path["BASELINE"],
                conservative_path_aggregate=candidate_by_path["CONSERVATIVE"],
                baseline_reference_by_path=(
                    baseline_by_path["BASELINE"],
                    baseline_by_path["CONSERVATIVE"],
                ),
            )
        q50 = decisions.get(StrategyIdentity.V2A_Q50)
        q67 = decisions.get(StrategyIdentity.V2A_Q67)
        if q50 is None:
            q50 = PromotionDecision(
                StrategyIdentity.V2A_Q50,
                baseline_by_path["CONSERVATIVE"],
                False,
                (),
                ("PREFLIGHT_ELIMINATED",),
            )
        if q67 is None:
            q67 = PromotionDecision(
                StrategyIdentity.V2A_Q67,
                baseline_by_path["CONSERVATIVE"],
                False,
                (),
                ("PREFLIGHT_ELIMINATED",),
            )
        selection = select_walk_forward_candidate(q50=q50, q67=q67)
        published = publish_walk_forward_report(
            output_dir=output_root / "results",
            canonical_economics={
                "experiment_identity": bundle.experiment_identity,
                "preflight_hash": bundle.report.content_hash,
                "baseline_by_path": baseline_by_path,
                "promotion_decisions": tuple(decisions.values()),
                "selection": selection,
            },
            diagnostics={
                "capacity_probe": probe,
                "effective_workers": effective_workers,
                "multiprocessing_start_method": batch.multiprocessing_start_method,
                "parent_peak_rss_bytes": batch.parent_peak_rss_bytes,
                "aggregate_worker_peak_rss_bytes": batch.aggregate_worker_peak_rss_bytes,
            },
        )
        return published.output_dir
