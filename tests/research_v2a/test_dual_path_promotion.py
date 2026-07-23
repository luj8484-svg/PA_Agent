from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from pa_agent.research_v2a.domain import StrategyIdentity
from pa_agent.research_v2a.walk_forward import (
    aggregate_fold_performance,
    evaluate_dual_path_promotion,
)
from tests.research_v2a.test_promotion import _baseline_folds, _candidate_folds


def test_profitable_baseline_path_cannot_hide_losing_conservative_path() -> None:
    candidate_baseline = aggregate_fold_performance(
        _candidate_folds(), initial_capital_per_fold=Decimal("10000")
    )
    losing_folds = tuple(
        replace(
            fold,
            net_pnl=-abs(fold.net_pnl),
            gross_profit=Decimal("10"),
            gross_loss=Decimal("-20"),
        )
        for fold in _candidate_folds()
    )
    candidate_conservative = aggregate_fold_performance(
        losing_folds, initial_capital_per_fold=Decimal("10000")
    )
    baseline_reference = aggregate_fold_performance(
        _baseline_folds(), initial_capital_per_fold=Decimal("10000")
    )

    decision = evaluate_dual_path_promotion(
        candidate=StrategyIdentity.V2A_Q50,
        baseline_path_aggregate=candidate_baseline,
        conservative_path_aggregate=candidate_conservative,
        baseline_reference_by_path=(baseline_reference, baseline_reference),
    )

    assert not decision.passed
    assert decision.baseline_path_decision.passed
    assert not decision.conservative_path_decision.passed
    assert "CONSERVATIVE:TOTAL_NET_PNL" in decision.failure_reasons
    assert "CONSERVATIVE:PROFIT_FACTOR" in decision.failure_reasons
