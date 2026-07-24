import json
from decimal import Decimal

import pytest

from pa_agent.research_2d.attribution import (
    INPUT_MISMATCH,
    POST_EXIT_DIAGNOSTIC_FIELDS,
    STRATEGY_INPUT_FIELDS,
    AttributionInputMismatch,
    _trade_id,
    _verify_bound_files,
    calculate_excursions,
    cost_attribution,
    planned_reward_values,
    reconcile_archive,
    subgroup_attribution,
)


def _bar(time: int, *, high: str, low: str) -> dict[str, object]:
    return {"open_time_utc_ms": time, "high": high, "low": low}


@pytest.mark.parametrize(
    ("side", "exit_price", "rows", "mfe", "mae"),
    [
        (
            "LONG",
            Decimal("102"),
            [
                _bar(0, high="105", low="98"),
                _bar(60_000, high="103", low="99"),
                _bar(120_000, high="102", low="101"),
            ],
            "5",
            "2",
        ),
        (
            "SHORT",
            Decimal("98"),
            [
                _bar(0, high="102", low="95"),
                _bar(60_000, high="101", low="97"),
                _bar(120_000, high="99", low="98"),
            ],
            "5",
            "2",
        ),
    ],
)
def test_mfe_mae_direction_is_correct(side, exit_price, rows, mfe, mae) -> None:
    result = calculate_excursions(
        side=side,
        entry_price=Decimal("100"),
        exit_price=exit_price,
        quantity=Decimal("1"),
        initial_risk=Decimal("10"),
        entry_time=0,
        exit_time=120_000,
        trade_rows=rows,
        mark_times={0, 60_000, 120_000},
        target_price=Decimal("105") if side == "LONG" else Decimal("95"),
        include_exit_bar_extremes=False,
    )

    assert result["MFE_usdt"] == mfe
    assert result["MAE_usdt"] == mae


def test_missing_mark_minute_fails_closed_for_mfe_mae() -> None:
    result = calculate_excursions(
        side="LONG",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        initial_risk=Decimal("10"),
        entry_time=0,
        exit_time=60_000,
        trade_rows=[_bar(0, high="102", low="99"), _bar(60_000, high="101", low="101")],
        mark_times={0},
        target_price=Decimal("110"),
        include_exit_bar_extremes=False,
    )

    assert result == {"availability": "MFE_MAE_UNAVAILABLE"}


def test_funding_sign_and_economic_total_cost_are_correct() -> None:
    row = {
        "fee": "150.775458120",
        "slippage_cost": "40.57374866602492077111457400",
        "funding_cashflow": "-24.7758397568927621730",
        "net_pnl": "-23.4997178768927621730",
        "availability": "AVAILABLE",
        "MFE_usdt": "1000",
        "economic_cost": "216.1250465429176829441145740",
        "initial_risk_usdt": "50",
        "realized_R_multiple": "-0.46999435753785524346",
    }

    result = cost_attribution([row])

    assert result["funding_income"] == "0"
    assert result["funding_expense"] == "24.7758397568927621730"
    assert result["economic_total_cost"] == "216.125046542918"


def test_planned_net_r_deducts_reserved_cost_once() -> None:
    values = planned_reward_values(
        {
            "quantity": "2",
            "expected_entry_fill_price": "100",
            "expected_take_profit_fill_price": "110",
            "side": "LONG",
            "entry_fee": "1",
            "exit_fee_reserve": "1",
            "funding_reserve": "2",
            "planned_risk": "10",
        }
    )

    assert values["planned_gross_reward_risk_ratio"] == Decimal("2")
    assert values["planned_net_reward_risk_ratio"] == Decimal("1.6")


def test_post_exit_diagnostics_cannot_be_strategy_inputs() -> None:
    assert STRATEGY_INPUT_FIELDS.isdisjoint(POST_EXIT_DIAGNOSTIC_FIELDS)


def _group_row(index: int) -> dict[str, object]:
    return {
        "symbol": "BTCUSDT" if index < 95 else "ETHUSDT",
        "side": "LONG" if index < 103 else "SHORT",
        "protective_outcome": "TIME_EXIT",
        "trend_regime": "HIGH",
        "volatility_regime": "MEDIUM",
        "breakout_regime": "HIGH",
        "planned_net_reward_risk_ratio": "0.8",
        "holding_minutes": 2_880,
        "entry_time": "2024-10-01T00:00:00Z",
        "net_pnl": "1",
        "gross_pnl": "2",
        "realized_R_multiple": "0.1",
        "availability": "AVAILABLE",
        "MFE_R": "0.5",
        "MAE_R": "0.2",
        "economic_cost": "1",
    }


def test_all_subgroup_dimension_counts_reconcile_to_169() -> None:
    result = subgroup_attribution([_group_row(index) for index in range(169)])

    for groups in result["groups"].values():
        assert sum(group["trade_count"] for group in groups.values()) == 169


def test_trade_ids_are_unique_for_distinct_accepted_trades() -> None:
    assert _trade_id({"position_id": "one"}) != _trade_id({"position_id": "two"})


def test_archive_reconciliation_matches_frozen_btc_eth_and_long_short() -> None:
    rows = [
        {"symbol": "BTCUSDT", "side": "LONG", "net_pnl": "-63.3887027759587928435"},
        {"symbol": "ETHUSDT", "side": "LONG", "net_pnl": "129.8906609637964036865"},
        {"symbol": "ETHUSDT", "side": "SHORT", "net_pnl": "-90.0016760647303730160"},
        *({"symbol": "BTCUSDT", "side": "LONG", "net_pnl": "0"} for _ in range(166)),
    ]
    report = {
        "by_symbol": {
            "BTCUSDT": {"net_pnl_usdt": "-63.3887027759587928435"},
            "ETHUSDT": {"net_pnl_usdt": "39.8889848990660306705"},
        },
        "by_side": {
            "LONG": {"net_pnl_usdt": "66.5019581878376108430"},
            "SHORT": {"net_pnl_usdt": "-90.0016760647303730160"},
        },
    }

    reconcile_archive(rows, report)


def test_manifest_hash_mismatch_fails_closed(tmp_path) -> None:
    (tmp_path / "data.json").write_text("changed", encoding="utf-8")
    (tmp_path / "result_manifest.json").write_text(
        json.dumps({"file_sha256": {"data.json": "0" * 64}}), encoding="utf-8"
    )

    with pytest.raises(AttributionInputMismatch, match=INPUT_MISMATCH):
        _verify_bound_files(tmp_path)
