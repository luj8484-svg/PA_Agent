from dataclasses import replace
from decimal import Decimal

import pytest

from pa_agent.research_2d.runner import Scenario
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.versions import MAX_HOLD_VERSION
from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS, StrategyIdentity
from pa_agent.research_v2a.preflight import (
    PREFLIGHT_FAILED,
    PREFLIGHT_PASSED,
    CandidatePreflightReport,
    CandidatePreflightStrategyResult,
    FoldPreflightResult,
)
from pa_agent.research_v2a.walk_forward import build_walk_forward_tasks


def _strategy_result(fold_id: str, strategy: StrategyIdentity) -> CandidatePreflightStrategyResult:
    ids = tuple(f"cand_{fold_id.lower()}{index:020x}" for index in range(20))
    return CandidatePreflightStrategyResult(
        strategy_identity=strategy,
        threshold=None if strategy is StrategyIdentity.V1_BASELINE else Decimal("1"),
        validation_candidate_count=20,
        accepted_candidate_count=20,
        rejected_candidate_count=0,
        retention_rate=Decimal("1"),
        accepted_by_symbol=(("BTCUSDT", 10), ("ETHUSDT", 10)),
        accepted_by_side=(("LONG", 10), ("SHORT", 10)),
        accepted_candidate_ids=ids,
        accepted_candidate_content_hash="a" * 64,
    )


def _preflight(
    eligible: tuple[StrategyIdentity, ...],
) -> CandidatePreflightReport:
    folds = tuple(
        FoldPreflightResult(
            fold_id=fold.fold_id,
            training_candidate_count=20,
            training_candidate_content_hash="b" * 64,
            threshold_manifest_hash="c" * 64,
            raw_validation_candidate_count=20,
            raw_validation_candidate_content_hash="d" * 64,
            execution_horizon_rejected_count=0,
            execution_horizon_rejected_candidate_ids=(),
            execution_horizon_decision_content_hash="9" * 64,
            validation_candidate_count=20,
            validation_candidate_content_hash="d" * 64,
            baseline=_strategy_result(fold.fold_id, StrategyIdentity.V1_BASELINE),
            q50=_strategy_result(fold.fold_id, StrategyIdentity.V2A_Q50),
            q67=_strategy_result(fold.fold_id, StrategyIdentity.V2A_Q67),
        )
        for fold in WALK_FORWARD_FOLDS
    )
    return CandidatePreflightReport(
        schema_version="V2A_CANDIDATE_PREFLIGHT_V2",
        status=PREFLIGHT_PASSED if eligible else PREFLIGHT_FAILED,
        dataset_content_hash="d" * 64,
        candidate_content_hash="e" * 64,
        candidate_count=100,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        execution_horizon_gate_version="V2A_EXECUTION_HORIZON_GATE_V1",
        execution_time_config_content_hash=execution_time_config(
            entry_delay_minutes=1,
            exit_delay_minutes=1,
        ).config_content_hash,
        maximum_holding_minutes=2880,
        max_hold_version=MAX_HOLD_VERSION,
        code_commit="f" * 40,
        dependency_lock_hash="1" * 64,
        fold_results=folds,
        eligible_strategies=eligible,
        eligible_task_count=4 * len(eligible),
        elimination_reasons=(),
    )


BASE = Scenario("BASE_1X", Decimal("1"), Decimal("1"))


@pytest.mark.parametrize(
    ("eligible", "expected"),
    [
        ((), 0),
        ((StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50), 8),
        (
            (
                StrategyIdentity.V1_BASELINE,
                StrategyIdentity.V2A_Q50,
                StrategyIdentity.V2A_Q67,
            ),
            12,
        ),
    ],
)
def test_registry_has_strict_zero_eight_or_twelve_tasks(eligible, expected) -> None:
    tasks = build_walk_forward_tasks(
        preflight=_preflight(eligible),
        folds=WALK_FORWARD_FOLDS,
        baseline_scenario=BASE,
    )

    assert len(tasks) == expected
    assert len({task.key for task in tasks}) == expected
    assert all(task.authority == "NATIVE_PRIMARY" for task in tasks)
    assert all(task.scenario.name == "BASE_1X" for task in tasks)


def test_preflight_eliminated_candidate_never_enters_registry() -> None:
    tasks = build_walk_forward_tasks(
        preflight=_preflight((StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50)),
        folds=WALK_FORWARD_FOLDS,
        baseline_scenario=BASE,
    )

    assert all(task.strategy_identity is not StrategyIdentity.V2A_Q67 for task in tasks)


def test_non_baseline_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="BASE_1X"):
        build_walk_forward_tasks(
            preflight=_preflight((StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50)),
            folds=WALK_FORWARD_FOLDS,
            baseline_scenario=Scenario("COMBINED_2X", Decimal("2"), Decimal("2")),
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: replace(report, schema_version="V2A_CANDIDATE_PREFLIGHT_V1"),
        lambda report: replace(
            report,
            fold_results=(
                replace(report.fold_results[0], raw_validation_candidate_count=21),
                *report.fold_results[1:],
            ),
        ),
        lambda report: replace(
            report,
            fold_results=(
                replace(
                    report.fold_results[0],
                    execution_horizon_rejected_count=1,
                    execution_horizon_rejected_candidate_ids=(
                        report.fold_results[0].baseline.accepted_candidate_ids[0],
                    ),
                ),
                *report.fold_results[1:],
            ),
        ),
        lambda report: replace(
            report,
            fold_results=(
                replace(
                    report.fold_results[0],
                    q50=replace(
                        report.fold_results[0].q50,
                        accepted_candidate_ids=("cand_outside00000000000000",),
                        accepted_candidate_count=1,
                        rejected_candidate_count=19,
                    ),
                ),
                *report.fold_results[1:],
            ),
        ),
    ],
)
def test_registry_fails_closed_on_stale_or_inconsistent_horizon_contract(mutate) -> None:
    report = _preflight((StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50))

    with pytest.raises(ValueError, match=r"Execution Horizon|Preflight schema"):
        build_walk_forward_tasks(
            preflight=mutate(report),
            folds=WALK_FORWARD_FOLDS,
            baseline_scenario=BASE,
        )
