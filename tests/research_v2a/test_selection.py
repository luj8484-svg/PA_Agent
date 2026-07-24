from dataclasses import replace
from decimal import Decimal

from pa_agent.research_v2a.domain import StrategyIdentity
from pa_agent.research_v2a.walk_forward import (
    V2A_WALK_FORWARD_FAILED,
    select_walk_forward_candidate,
)
from tests.research_v2a.test_promotion import _decision


def test_only_passing_candidate_is_selected() -> None:
    q50 = _decision()
    q67 = replace(q50, candidate=StrategyIdentity.V2A_Q67, passed=False)
    assert select_walk_forward_candidate(q50=q50, q67=q67).selected is StrategyIdentity.V2A_Q50


def test_both_fail_returns_frozen_failure_and_no_candidate() -> None:
    q50 = replace(_decision(), passed=False)
    q67 = replace(q50, candidate=StrategyIdentity.V2A_Q67)
    selection = select_walk_forward_candidate(q50=q50, q67=q67)
    assert selection.selected is None
    assert selection.conclusion == V2A_WALK_FORWARD_FAILED


def test_both_pass_default_to_q50() -> None:
    q50 = _decision()
    q67 = replace(q50, candidate=StrategyIdentity.V2A_Q67)
    assert select_walk_forward_candidate(q50=q50, q67=q67).selected is StrategyIdentity.V2A_Q50


def test_q67_requires_every_frozen_superiority_condition() -> None:
    q50 = _decision()
    q67_aggregate = replace(
        q50.aggregate,
        aggregate_profit_factor=q50.aggregate.aggregate_profit_factor + Decimal("0.10"),
        total_net_pnl=q50.aggregate.total_net_pnl * Decimal("1.25"),
        median_fold_max_drawdown=q50.aggregate.median_fold_max_drawdown,
    )
    q67 = replace(
        q50,
        candidate=StrategyIdentity.V2A_Q67,
        aggregate=q67_aggregate,
    )
    assert select_walk_forward_candidate(q50=q50, q67=q67).selected is StrategyIdentity.V2A_Q67

    too_low_pf = replace(
        q67,
        aggregate=replace(
            q67.aggregate,
            aggregate_profit_factor=q50.aggregate.aggregate_profit_factor + Decimal("0.099"),
        ),
    )
    assert (
        select_walk_forward_candidate(q50=q50, q67=too_low_pf).selected is StrategyIdentity.V2A_Q50
    )
