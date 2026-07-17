from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pa_agent.research_backtest.domain.enums import Side


@given(
    st.lists(st.tuples(st.text(min_size=1), st.integers()), min_size=1, unique_by=lambda x: x[0])
)
def test_property_canonical_mapping_order_is_irrelevant(items) -> None:
    from pa_agent.research_backtest.simulation.identity import canonical_2c_sha256

    assert canonical_2c_sha256(dict(items)) == canonical_2c_sha256(dict(reversed(items)))


@given(st.integers(min_value=1, max_value=1_000_000))
def test_property_config_identity_is_stable_for_decimal_balances(balance: int) -> None:
    from pa_agent.research_backtest.simulation.domain import make_simulation_config

    args = {
        "symbols": ("BTCUSDT", "ETHUSDT"),
        "simulation_start_utc_ms": 0,
        "simulation_end_exit_open_utc_ms": 60_000,
        "initial_wallet_balance": Decimal(balance),
        "cost_model_version": "COST_V1",
        "funding_model_version": "FUNDING_V1",
        "two_a_version": "2A_V1",
        "two_b_planner_version": "2B_V1",
        "two_b_planner_config_hash": "a" * 64,
        "code_commit": "b" * 40,
        "dependency_lock_hash": "c" * 64,
    }
    assert make_simulation_config(**args) == make_simulation_config(**args)


@given(
    st.sampled_from((Side.LONG, Side.SHORT)),
    st.decimals(min_value="-0.02", max_value="0.02", allow_nan=False, allow_infinity=False),
)
def test_property_funding_delta_is_side_antisymmetric(side: Side, rate: Decimal) -> None:
    from pa_agent.research_backtest.simulation.funding import (
        FundingRecord,
        FundingSettlement,
        settle_funding,
    )
    from tests.research_backtest.simulation.test_funding_liquidation import position

    record = FundingRecord("f", "BTCUSDT", 60_000, rate, Decimal("100"), "a" * 64)
    large = replace(position(side), remaining_funding_reserve=Decimal("1000"))
    opposite = replace(
        large,
        side=Side.SHORT if side is Side.LONG else Side.LONG,
        position_id="opposite",
    )
    first = settle_funding(large, record)
    second = settle_funding(opposite, record)
    assert isinstance(first, FundingSettlement) and isinstance(second, FundingSettlement)
    assert first.wallet_delta == -second.wallet_delta


@given(st.decimals(min_value="1", max_value="100000", allow_nan=False, allow_infinity=False))
def test_property_fixed_full_margin_long_liquidation_is_zero(price: Decimal) -> None:
    from pa_agent.research_backtest.simulation.liquidation import estimated_liquidation
    from tests.research_backtest.simulation.test_funding_liquidation import maintenance, position

    pos = replace(
        position(),
        entry_price=price,
        initial_margin=price * Decimal("2"),
        isolated_margin_balance=price * Decimal("2"),
    )
    assert estimated_liquidation(pos, maintenance(), 60_000).liquidation_price == 0


@given(st.decimals(min_value="0", max_value="0.05", allow_nan=False, allow_infinity=False))
def test_property_protective_fill_is_always_adverse(slippage: Decimal) -> None:
    from pa_agent.research_backtest.simulation.triggers import (
        TriggerCandidate,
        TriggerKind,
        protective_fill_price,
    )

    candidate = TriggerCandidate(
        TriggerKind.STOP,
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        "TRADE_1M",
        False,
        Decimal("0"),
    )
    assert protective_fill_price(Side.LONG, candidate, slippage, Decimal("0.1")) <= 100
    assert protective_fill_price(Side.SHORT, candidate, slippage, Decimal("0.1")) >= 100


@given(st.integers(min_value=1, max_value=50))
def test_property_ambiguity_path_count_is_globally_bounded(iterations: int) -> None:
    from pa_agent.research_backtest.simulation.ambiguity import resolve_all_paths
    from pa_agent.research_backtest.simulation.domain import PathKind
    from pa_agent.research_backtest.simulation.triggers import TriggerCandidate, TriggerKind

    candidates = (
        TriggerCandidate(
            TriggerKind.STOP,
            Decimal("99"),
            Decimal("99"),
            Decimal("100"),
            "TRADE_1M",
            False,
            Decimal("99"),
        ),
        TriggerCandidate(
            TriggerKind.TAKE_PROFIT,
            Decimal("101"),
            Decimal("101"),
            Decimal("100"),
            "TRADE_1M",
            False,
            Decimal("101"),
        ),
    )
    paths = (PathKind.BASELINE, PathKind.CONSERVATIVE)
    for _ in range(iterations):
        result = resolve_all_paths(paths, object(), candidates)
        assert len(result) <= 2
        paths = tuple(item.path_kind for item in result)


@given(st.decimals(min_value="0", max_value="9000", allow_nan=False, allow_infinity=False))
def test_property_ledger_obligation_cannot_replay(amount: Decimal) -> None:
    from pa_agent.research_backtest.simulation.domain import (
        initial_engine_state,
        make_simulation_config,
    )
    from pa_agent.research_backtest.simulation.ledger import (
        LedgerEntry,
        LedgerKind,
        LedgerReplayError,
        reduce_ledger,
    )

    config = make_simulation_config(
        symbols=("BTCUSDT", "ETHUSDT"),
        simulation_start_utc_ms=0,
        simulation_end_exit_open_utc_ms=60_000,
        initial_wallet_balance=Decimal("10000"),
        cost_model_version="COST_V1",
        funding_model_version="FUNDING_V1",
        two_a_version="2A_V1",
        two_b_planner_version="2B_V1",
        two_b_planner_config_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )
    item = LedgerEntry(
        "same",
        0,
        LedgerKind.MARGIN_LOCK,
        Decimal("0"),
        amount,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )
    first = reduce_ledger(initial_engine_state(config), (item,))
    with pytest.raises(LedgerReplayError):
        reduce_ledger(first, (item,))


@given(st.integers(min_value=1, max_value=4))
def test_property_paths_have_identical_economics_without_ambiguity(minutes: int) -> None:
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.simulation.inputs import SimulationInputs
    from tests.research_backtest.simulation.test_minute_engine_output import (
        config,
        dependencies,
        minute,
    )

    slices = tuple(minute(index * 60_000) for index in range(minutes + 1))
    result = run_simulation(
        SimulationInputs(slices, (), ()),
        config(simulation_end_exit_open_utc_ms=minutes * 60_000),
        dependencies(),
    )

    def economics(path):
        return tuple(
            (
                tuple(
                    (event.event_time_utc_ms, event.stage, event.kind, event.subject_id)
                    for event in item.events
                ),
                item.fills,
                item.ledger_entries,
                item.trades,
                tuple(point.equity for point in item.equity_points),
            )
            for item in path.minute_results
        )

    assert len(result.paths) == 2
    assert economics(result.paths[0]) == economics(result.paths[1])


@given(st.decimals(min_value="0.2", max_value="0.8", places=1))
def test_property_first_ambiguity_is_the_first_allowed_divergence(
    take_profit_offset: Decimal,
) -> None:
    from pa_agent.research_backtest.simulation.domain import PathKind, initial_engine_state
    from pa_agent.research_backtest.simulation.engine import process_minute
    from tests.research_backtest.simulation.test_funding_liquidation import position
    from tests.research_backtest.simulation.test_minute_engine_output import (
        config,
        dependencies,
        minute,
    )

    cfg = config()
    pos = replace(
        position(),
        stop_trigger_price=Decimal("99"),
        take_profit_trigger_price=Decimal("100") + take_profit_offset,
    )

    def state(kind):
        return replace(
            initial_engine_state(cfg, kind),
            positions=(pos,),
            locked_initial_margin=pos.initial_margin,
            locked_fee_reserve=pos.remaining_fee_reserve,
            locked_funding_reserve=pos.remaining_funding_reserve,
        )

    baseline_before = state(PathKind.BASELINE)
    conservative_before = state(PathKind.CONSERVATIVE)
    assert replace(conservative_before, path_kind=PathKind.BASELINE) == baseline_before
    value = minute()
    value = replace(
        value,
        trade_bars=(
            replace(
                value.trade_bars[0],
                low=Decimal("98.5"),
                high=Decimal("101"),
                close=Decimal("100"),
            ),
        ),
        mark_bars=(
            replace(
                value.mark_bars[0],
                low=Decimal("98.5"),
                high=Decimal("101"),
                close=Decimal("100"),
            ),
        ),
    )
    baseline_after = process_minute(baseline_before, value, cfg, dependencies())
    conservative_after = process_minute(conservative_before, value, cfg, dependencies())
    assert baseline_after.fills[0].fill_price != conservative_after.fills[0].fill_price
