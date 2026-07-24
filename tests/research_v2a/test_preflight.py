from pa_agent.research_backtest.domain.enums import MarketView
from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS, StrategyIdentity
from pa_agent.research_v2a.preflight import (
    PREFLIGHT_FAILED,
    PREFLIGHT_PASSED,
    run_candidate_preflight,
)
from tests.research_v2a.helpers import make_candidate


def _population(validation_strength: str = "4", *, first_validation_strength: str | None = None):
    candidates = []
    hexadecimal = "abcdef"
    for fold_index, fold in enumerate(WALK_FORWARD_FOLDS):
        for index, strength in enumerate(("1", "2", "4", "5")):
            candidates.append(
                make_candidate(
                    decision_time_utc_ms=fold.training_start_utc_ms
                    + (fold_index * 4 + index) * 14_400_000,
                    strength=strength,
                    suffix=hexadecimal[(fold_index + index) % len(hexadecimal)],
                )
            )
        for index in range(20):
            fold_validation_strength = (
                first_validation_strength
                if fold_index == 0 and first_validation_strength is not None
                else validation_strength
            )
            candidates.append(
                make_candidate(
                    decision_time_utc_ms=(
                        fold.validation_start_utc_ms + (index + 1) * 14_400_000 - 1
                    ),
                    strength=fold_validation_strength,
                    symbol="BTCUSDT" if index % 2 == 0 else "ETHUSDT",
                    market_view=MarketView.LONG if index % 4 < 2 else MarketView.SHORT,
                    suffix=hexadecimal[index % len(hexadecimal)],
                )
            )
    return tuple(candidates)


def _run(candidates):
    return run_candidate_preflight(
        folds=WALK_FORWARD_FOLDS,
        strategy_candidates=candidates,
        dataset_content_hash="1" * 64,
        code_commit="2" * 40,
        dependency_lock_hash="3" * 64,
    )


def test_preflight_reports_counts_thresholds_structure_and_twelve_task_eligibility() -> None:
    report = _run(_population())

    assert report.status == PREFLIGHT_PASSED
    assert report.eligible_task_count == 12
    assert report.eligible_strategies == (
        StrategyIdentity.V1_BASELINE,
        StrategyIdentity.V2A_Q50,
        StrategyIdentity.V2A_Q67,
    )
    assert len(report.fold_results) == 4
    for result in report.fold_results:
        assert result.raw_validation_candidate_count == 20
        assert result.execution_horizon_rejected_count == 0
        assert result.execution_horizon_rejected_candidate_ids == ()
        assert result.validation_candidate_count == 20
        assert result.q50.accepted_candidate_count == 20
        assert result.q67.accepted_candidate_count == 20
        assert result.q50.accepted_by_symbol == (("BTCUSDT", 10), ("ETHUSDT", 10))
        assert result.q50.accepted_by_side == (("LONG", 10), ("SHORT", 10))
        assert result.q50.retention_rate == 1
        assert result.q50.accepted_candidate_content_hash
    assert not report.elimination_reasons
    assert len(report.content_hash) == 64


def test_preflight_registers_eight_tasks_when_only_q50_survives() -> None:
    report = _run(_population(first_validation_strength="3"))

    assert report.status == PREFLIGHT_PASSED
    assert report.eligible_task_count == 8
    assert report.eligible_strategies == (
        StrategyIdentity.V1_BASELINE,
        StrategyIdentity.V2A_Q50,
    )
    assert any(reason.startswith("V2A_Q67:") for reason in report.elimination_reasons)


def test_preflight_registers_zero_tasks_when_both_candidates_fail() -> None:
    report = _run(_population(first_validation_strength="1.5"))

    assert report.status == PREFLIGHT_FAILED
    assert report.eligible_task_count == 0
    assert not report.eligible_strategies
    assert any(reason.startswith("V2A_Q50:") for reason in report.elimination_reasons)
    assert any(reason.startswith("V2A_Q67:") for reason in report.elimination_reasons)


def test_future_candidate_fails_closed_before_threshold_calculation() -> None:
    future = make_candidate(
        decision_time_utc_ms=WALK_FORWARD_FOLDS[-1].validation_end_utc_ms + 1,
        strength="4",
    )

    try:
        _run((*_population(), future))
    except ValueError as exc:
        assert "outside V2-A development boundary" in str(exc)
    else:
        raise AssertionError("future Candidate must fail closed")


def test_q67_accepted_set_is_always_subset_of_q50() -> None:
    report = _run(_population())

    for fold in report.fold_results:
        assert set(fold.q67.accepted_candidate_ids) <= set(fold.q50.accepted_candidate_ids)


def test_execution_horizon_gate_precedes_all_strategy_identity_filters() -> None:
    fold = WALK_FORWARD_FOLDS[0]
    late = make_candidate(
        decision_time_utc_ms=fold.validation_end_utc_ms,
        strength="10",
        symbol="ETHUSDT",
        suffix="f",
    )

    report = _run((*_population(), late))
    result = report.fold_results[0]

    assert result.raw_validation_candidate_count == 21
    assert result.validation_candidate_count == 20
    assert result.execution_horizon_rejected_count == 1
    assert result.execution_horizon_rejected_candidate_ids == (late.candidate_id,)
    assert late.candidate_id not in result.baseline.accepted_candidate_ids
    assert late.candidate_id not in result.q50.accepted_candidate_ids
    assert late.candidate_id not in result.q67.accepted_candidate_ids
    assert set(result.q67.accepted_candidate_ids) <= set(result.q50.accepted_candidate_ids)
