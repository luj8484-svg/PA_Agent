from dataclasses import replace
from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.enums import Side
from tests.research_backtest.simulation.test_funding_liquidation import position
from tests.research_backtest.simulation.test_inputs_and_invalid import bar


def test_open_gap_priority_liquidation_over_stop_tp() -> None:
    from pa_agent.research_backtest.simulation.triggers import (
        TriggerKind,
        choose_open_gap_trigger,
        discover_open_gap_candidates,
    )

    pos = replace(
        position(),
        stop_trigger_price=Decimal("105"),
        take_profit_trigger_price=Decimal("95"),
    )
    candidates = discover_open_gap_candidates(pos, bar(), bar(), Decimal("101"))
    assert {item.kind for item in candidates} == {
        TriggerKind.LIQUIDATION,
        TriggerKind.STOP,
        TriggerKind.TAKE_PROFIT,
    }
    assert choose_open_gap_trigger(candidates).kind is TriggerKind.LIQUIDATION


def test_short_open_gap_priority_is_symmetric() -> None:
    from pa_agent.research_backtest.simulation.triggers import (
        TriggerKind,
        choose_open_gap_trigger,
        discover_open_gap_candidates,
    )

    pos = replace(
        position(Side.SHORT),
        stop_trigger_price=Decimal("95"),
        take_profit_trigger_price=Decimal("105"),
    )
    candidates = discover_open_gap_candidates(pos, bar(), bar(), Decimal("99"))
    assert choose_open_gap_trigger(candidates).kind is TriggerKind.LIQUIDATION


def test_stop_tp_use_trade_and_liquidation_uses_mark() -> None:
    from pa_agent.research_backtest.simulation.triggers import discover_intraminute_candidates

    trade = replace(bar(), low=Decimal("89"), high=Decimal("121"))
    mark = replace(bar(), low=Decimal("80"), high=Decimal("106"))
    candidates = discover_intraminute_candidates(position(), trade, mark, Decimal("85"))
    sources = {item.kind.value: item.source for item in candidates}
    assert sources == {
        "LIQUIDATION": "MARK_1M",
        "STOP": "TRADE_1M",
        "TAKE_PROFIT": "TRADE_1M",
    }


@pytest.mark.parametrize(
    ("side", "reference", "expected"),
    [
        (Side.LONG, "100", "99.9"),
        (Side.SHORT, "100", "100.1"),
    ],
)
def test_protective_fill_applies_slippage_once_and_adverse_tick(
    side: Side, reference: str, expected: str
) -> None:
    from pa_agent.research_backtest.simulation.triggers import (
        TriggerCandidate,
        TriggerKind,
        protective_fill_price,
    )

    candidate = TriggerCandidate(
        TriggerKind.STOP,
        Decimal(reference),
        Decimal(reference),
        Decimal(reference),
        "TRADE_1M",
        True,
        Decimal("0"),
    )
    assert protective_fill_price(side, candidate, Decimal("0.001"), Decimal("0.1")) == Decimal(
        expected
    )


def candidate(kind: str, distance_price: str, equity: str):
    from pa_agent.research_backtest.simulation.triggers import TriggerCandidate, TriggerKind

    return TriggerCandidate(
        TriggerKind(kind),
        Decimal(distance_price),
        Decimal(distance_price),
        Decimal("100"),
        "TRADE_1M",
        False,
        Decimal(equity),
    )


def test_baseline_uses_closest_percentage_distance() -> None:
    from pa_agent.research_backtest.simulation.ambiguity import resolve_ambiguity
    from pa_agent.research_backtest.simulation.domain import PathKind

    chosen = resolve_ambiguity(
        PathKind.BASELINE,
        object(),
        (candidate("STOP", "98", "9900"), candidate("TAKE_PROFIT", "105", "10100")),
    )
    assert chosen.kind.value == "STOP"


def test_conservative_uses_lowest_minute_end_equity() -> None:
    from pa_agent.research_backtest.simulation.ambiguity import resolve_ambiguity
    from pa_agent.research_backtest.simulation.domain import PathKind

    chosen = resolve_ambiguity(
        PathKind.CONSERVATIVE,
        object(),
        (candidate("STOP", "98", "9900"), candidate("TAKE_PROFIT", "105", "10100")),
    )
    assert chosen.kind.value == "STOP"


def test_equal_ambiguity_uses_liquidation_stop_tp_priority() -> None:
    from pa_agent.research_backtest.simulation.ambiguity import resolve_ambiguity
    from pa_agent.research_backtest.simulation.domain import PathKind

    chosen = resolve_ambiguity(
        PathKind.BASELINE,
        object(),
        (candidate("STOP", "99", "9900"), candidate("LIQUIDATION", "99", "9900")),
    )
    assert chosen.kind.value == "LIQUIDATION"


def test_twenty_ambiguities_never_grow_beyond_two_paths() -> None:
    from pa_agent.research_backtest.simulation.ambiguity import resolve_all_paths
    from pa_agent.research_backtest.simulation.domain import PathKind

    paths = (PathKind.BASELINE, PathKind.CONSERVATIVE)
    for _ in range(20):
        successors = resolve_all_paths(
            paths,
            object(),
            (candidate("STOP", "99", "9900"), candidate("TAKE_PROFIT", "101", "10010")),
        )
        assert len(successors) == 2
        paths = tuple(item.path_kind for item in successors)


def test_open_exited_position_is_excluded_from_intraminute_halt() -> None:
    from pa_agent.research_backtest.simulation.halt import (
        ExposureDisposition,
        uses_full_minute_extreme,
    )

    assert not uses_full_minute_extreme(ExposureDisposition.OPEN_EXITED)
    assert uses_full_minute_extreme(ExposureDisposition.INTRAMINUTE_EXITED)
    assert uses_full_minute_extreme(ExposureDisposition.HELD_TO_CLOSE)


def test_halt_is_absorbing_and_preserves_final_time_separately() -> None:
    from pa_agent.research_backtest.simulation.domain import PathState
    from pa_agent.research_backtest.simulation.halt import apply_halt
    from tests.research_backtest.simulation.test_ledger_account import state

    halted = apply_halt(state(), 60_000, "DRAWDOWN_10_PERCENT")
    later = apply_halt(halted, 120_000, "SECOND_BREACH")
    assert later.path_state is PathState.HALTED
    assert later.halt_trigger_time_utc_ms == 60_000
    assert later.final_processed_time_utc_ms is None


def test_drawdown_threshold_is_inclusive() -> None:
    from pa_agent.research_backtest.simulation.halt import drawdown_breached

    assert drawdown_breached(Decimal("100"), Decimal("90"))
    assert not drawdown_breached(Decimal("100"), Decimal("90.0001"))
