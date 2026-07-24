from decimal import Decimal

from pa_agent.research_2d.archive import build_archive_report


def test_failed_baseline_archive_uses_existing_trades_and_corrected_metrics() -> None:
    metric = {
        "net_return": "-0.0023499717876892762173",
        "annualized_return": "-0.00156976717412338",
        "profit_factor": "0.9885986917222877062239042784",
        "sharpe": "-0.0315984270796093",
        "win_rate": "0.4142011834319526627218934911",
        "trade_count": 2,
        "fees": "150.775458120",
        "slippage": "40.57374866602492077111457400",
        "funding": "-24.7758397568927621730",
        "maximum_drawdown": "0.0297311850219874",
    }
    trades = [
        {"symbol": "BTCUSDT", "side": "SHORT", "exit_reason": "TIME_EXIT", "net_pnl": "-2"},
        {"symbol": "ETHUSDT", "side": "LONG", "exit_reason": "PROTECTIVE", "net_pnl": "1"},
    ]

    report = build_archive_report(
        source_experiment_id="a" * 64,
        metric=metric,
        trades=trades,
        engine_peak_observed_drawdown=Decimal("0.0323942484534149"),
    )

    assert report["final_conclusion"] == "STRATEGY_FAILED_BASELINE_VALIDATION"
    assert report["drawdown"] == {
        "daily_close_max_drawdown": "0.0297311850219874",
        "engine_peak_observed_drawdown": "0.0323942484534149",
        "engine_peak_observed_drawdown_provenance": "INDEPENDENT_ACCEPTANCE_AUDIT",
    }
    assert report["costs_usdt"]["economic_total_cost"] == "216.125046542918"
    assert report["by_symbol"]["BTCUSDT"]["net_pnl_usdt"] == "-2"
    assert report["source_integrity"]["minute_engine_replayed"] is False
