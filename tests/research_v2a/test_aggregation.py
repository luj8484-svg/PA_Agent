from decimal import Decimal

import pytest

from pa_agent.research_v2a.walk_forward import (
    FoldPerformance,
    aggregate_fold_performance,
)


def fold(
    fold_id: str,
    *,
    net: str,
    gross_profit: str,
    gross_loss: str,
    drawdown: str,
    trades: int = 20,
    complete: bool = True,
    halted: bool = False,
) -> FoldPerformance:
    return FoldPerformance(
        fold_id=fold_id,
        net_pnl=Decimal(net),
        gross_profit=Decimal(gross_profit),
        gross_loss=Decimal(gross_loss),
        max_drawdown=Decimal(drawdown),
        trade_count=trades,
        symbol_net_pnl=(("BTCUSDT", Decimal(net) / 2), ("ETHUSDT", Decimal(net) / 2)),
        symbol_trade_counts=(("BTCUSDT", trades // 2), ("ETHUSDT", trades - trades // 2)),
        side_net_pnl=(("LONG", Decimal(net) / 2), ("SHORT", Decimal(net) / 2)),
        side_trade_counts=(("LONG", trades // 2), ("SHORT", trades - trades // 2)),
        reached_fold_end=complete,
        halted=halted,
        data_invalid=False,
        invariant_failures=(),
    )


def test_aggregate_uses_frozen_decimal_formulas_and_independent_medians() -> None:
    result = aggregate_fold_performance(
        (
            fold("F1", net="100", gross_profit="150", gross_loss="-50", drawdown=".01"),
            fold("F2", net="200", gross_profit="250", gross_loss="-50", drawdown=".04"),
            fold("F3", net="-50", gross_profit="50", gross_loss="-100", drawdown=".02"),
            fold("F4", net="150", gross_profit="200", gross_loss="-50", drawdown=".03"),
        ),
        initial_capital_per_fold=Decimal("10000"),
    )

    assert result.total_net_pnl == Decimal("400")
    assert result.aggregate_return == Decimal("0.01")
    assert result.aggregate_profit_factor == Decimal("2.6")
    assert result.median_fold_net_pnl == Decimal("125")
    assert result.median_fold_max_drawdown == Decimal("0.025")
    assert result.total_trade_count == 80


def test_zero_aggregate_gross_loss_uses_explicit_none() -> None:
    folds = tuple(
        fold(
            f"F{index}",
            net="10",
            gross_profit="10",
            gross_loss="0",
            drawdown=".01",
        )
        for index in range(1, 5)
    )
    assert (
        aggregate_fold_performance(
            folds, initial_capital_per_fold=Decimal("10000")
        ).aggregate_profit_factor
        is None
    )


@pytest.mark.parametrize("capital", ["0", "9999", "10001"])
def test_aggregation_requires_four_independent_10000_accounts(capital: str) -> None:
    folds = tuple(
        fold(f"F{index}", net="10", gross_profit="11", gross_loss="-1", drawdown=".01")
        for index in range(1, 5)
    )
    with pytest.raises(ValueError):
        aggregate_fold_performance(folds, initial_capital_per_fold=Decimal(capital))
