from __future__ import annotations

from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.canonical import canonical_decimal
from pa_agent.research_backtest.domain.plans import EntryExecutionPlan
from pa_agent.research_backtest.planning.cash import calculate_final_required_cash
from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
from tests.research_backtest.execution.fixtures.entry_plan_case import complete_entry_inputs


@pytest.mark.test_id("UT-CASH-001")
@pytest.mark.requirement_ids("2B-CASH-024")
def test_real_candidate_c28491_required_cash_is_identical_at_every_boundary() -> None:
    inputs = complete_entry_inputs(
        decision_close_override=Decimal("69566.10"),
        atr14_4h=Decimal("746.143128351688"),
        adverse_funding_rate_cap=Decimal("0.00300000"),
        wallet_balance=Decimal("10022.2967106094750140116"),
    )

    plan = build_entry_execution_plan(inputs)

    assert isinstance(plan, EntryExecutionPlan)
    canonical = calculate_final_required_cash(
        quantity=inputs.accepted_item.final_quantity,
        expected_entry_fill_price=inputs.sizing.expected_entry_fill_price,
        planned_exit_notional_price_basis=inputs.sizing.planned_exit_notional_price_basis,
        effective_fee_rate=inputs.cost.effective_fee_rate,
        effective_adverse_rate_cap=inputs.sizing.effective_adverse_rate_cap,
        funding_event_upper_bound=inputs.sizing.funding_event_upper_bound,
    )
    assert inputs.accepted_item.final_required_cash == plan.required_cash == canonical
    assert canonical_decimal(inputs.accepted_item.final_required_cash) == canonical_decimal(
        plan.required_cash
    )


@pytest.mark.test_id("UT-CASH-002")
@pytest.mark.requirement_ids("2B-CASH-025")
def test_canonical_cash_calculation_is_independent_of_ambient_decimal_context() -> None:
    import decimal

    original = decimal.getcontext().copy()
    try:
        decimal.getcontext().prec = 9
        low = calculate_final_required_cash(
            quantity=Decimal("0.017"),
            expected_entry_fill_price=Decimal("69573.1"),
            planned_exit_notional_price_basis=Decimal("71804.3"),
            effective_fee_rate=Decimal("0.0005"),
            effective_adverse_rate_cap=Decimal("0.00300000"),
            funding_event_upper_bound=6,
        )
        decimal.getcontext().prec = 50
        high = calculate_final_required_cash(
            quantity=Decimal("0.017"),
            expected_entry_fill_price=Decimal("69573.1"),
            planned_exit_notional_price_basis=Decimal("71804.3"),
            effective_fee_rate=Decimal("0.0005"),
            effective_adverse_rate_cap=Decimal("0.00300000"),
            funding_event_upper_bound=6,
        )
    finally:
        decimal.setcontext(original)
    assert low == high == Decimal("1205.916523700000")
