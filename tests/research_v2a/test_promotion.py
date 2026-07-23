from dataclasses import replace
from decimal import Decimal

from pa_agent.research_v2a.domain import StrategyIdentity
from pa_agent.research_v2a.walk_forward import (
    FoldPerformance,
    aggregate_fold_performance,
    evaluate_promotion,
)
from tests.research_v2a.test_aggregation import fold


def _candidate_folds() -> tuple[FoldPerformance, ...]:
    return (
        fold("F1", net="100", gross_profit="120", gross_loss="-20", drawdown=".01"),
        fold("F2", net="120", gross_profit="140", gross_loss="-20", drawdown=".02"),
        fold("F3", net="80", gross_profit="100", gross_loss="-20", drawdown=".03"),
        fold("F4", net="-10", gross_profit="20", gross_loss="-30", drawdown=".04"),
    )


def _baseline_folds() -> tuple[FoldPerformance, ...]:
    return (
        fold("F1", net="50", gross_profit="70", gross_loss="-20", drawdown=".02"),
        fold("F2", net="60", gross_profit="80", gross_loss="-20", drawdown=".03"),
        fold("F3", net="40", gross_profit="60", gross_loss="-20", drawdown=".04"),
        fold("F4", net="-20", gross_profit="20", gross_loss="-40", drawdown=".05"),
    )


def _decision(
    candidate_folds: tuple[FoldPerformance, ...] | None = None,
    baseline_folds: tuple[FoldPerformance, ...] | None = None,
):
    return evaluate_promotion(
        candidate=StrategyIdentity.V2A_Q50,
        aggregate=aggregate_fold_performance(
            candidate_folds or _candidate_folds(),
            initial_capital_per_fold=Decimal("10000"),
        ),
        baseline=aggregate_fold_performance(
            baseline_folds or _baseline_folds(),
            initial_capital_per_fold=Decimal("10000"),
        ),
    )


def test_all_thirteen_promotion_criteria_pass_as_strict_conjunction() -> None:
    decision = _decision()
    assert decision.passed
    assert len(decision.criteria) == 13
    assert all(criterion.passed for criterion in decision.criteria)


def test_each_promotion_criterion_can_be_strictly_failed() -> None:
    candidate = aggregate_fold_performance(
        _candidate_folds(), initial_capital_per_fold=Decimal("10000")
    )
    baseline = aggregate_fold_performance(
        _baseline_folds(), initial_capital_per_fold=Decimal("10000")
    )

    def evaluate(aggregate=candidate, baseline_aggregate=baseline):
        return evaluate_promotion(
            candidate=StrategyIdentity.V2A_Q50,
            aggregate=aggregate,
            baseline=baseline_aggregate,
        )

    two_positive = tuple(
        replace(item, net_pnl=Decimal("-1")) if item.fold_id in {"F3", "F4"} else item
        for item in _candidate_folds()
    )
    stronger_baseline = tuple(
        replace(item, net_pnl=Decimal("1000")) if item.fold_id in {"F1", "F2"} else item
        for item in _baseline_folds()
    )
    low_trade_fold = list(_candidate_folds())
    low_trade_fold[0] = replace(low_trade_fold[0], trade_count=9)
    concentrated = list(_candidate_folds())
    concentrated[0] = replace(concentrated[0], net_pnl=Decimal("1000"))
    incomplete = list(_candidate_folds())
    incomplete[0] = replace(incomplete[0], reached_fold_end=False, halted=True)
    invariant = list(_candidate_folds())
    invariant[0] = replace(invariant[0], invariant_failures=("LEDGER",))

    cases = (
        (_decision(two_positive), "POSITIVE_FOLD_COUNT"),
        (_decision(baseline_folds=stronger_baseline), "OUTPERFORM_BASELINE_FOLD_COUNT"),
        (evaluate(replace(candidate, total_net_pnl=Decimal("0"))), "TOTAL_NET_PNL"),
        (
            evaluate(replace(candidate, aggregate_profit_factor=Decimal("1.099"))),
            "PROFIT_FACTOR",
        ),
        (evaluate(replace(candidate, total_trade_count=59)), "TOTAL_TRADE_COUNT"),
        (_decision(tuple(low_trade_fold)), "MIN_FOLD_TRADE_COUNT"),
        (
            evaluate(replace(candidate, median_fold_net_pnl=Decimal("0"))),
            "MEDIAN_FOLD_NET_PNL",
        ),
        (
            evaluate(replace(candidate, median_fold_max_drawdown=Decimal("0.036"))),
            "MEDIAN_DRAWDOWN",
        ),
        (_decision(tuple(concentrated)), "FOLD_PROFIT_CONCENTRATION"),
        (
            evaluate(
                replace(
                    candidate,
                    symbol_net_pnl=(
                        ("BTCUSDT", Decimal("290")),
                        ("ETHUSDT", Decimal("0")),
                    ),
                )
            ),
            "SYMBOL_DIVERSIFICATION",
        ),
        (
            evaluate(
                replace(
                    candidate,
                    side_net_pnl=(
                        ("LONG", Decimal("290")),
                        ("SHORT", Decimal("0")),
                    ),
                )
            ),
            "SIDE_DIVERSIFICATION",
        ),
        (_decision(tuple(incomplete)), "COMPLETE_VALID_PATHS"),
        (_decision(tuple(invariant)), "INVARIANTS"),
    )
    assert len(cases) == 13
    for decision, expected_failure in cases:
        assert not decision.passed
        assert expected_failure in decision.failure_reasons


def test_halted_fold_never_promotes_or_enters_valid_aggregate() -> None:
    folds = list(_candidate_folds())
    folds[3] = replace(folds[3], halted=True, reached_fold_end=False)
    assert not _decision(tuple(folds)).passed
