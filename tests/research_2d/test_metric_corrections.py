from decimal import Decimal
from types import SimpleNamespace

from pa_agent.research_2d.metrics import economic_total_cost, summarize_path


def test_report_separates_daily_close_and_engine_peak_drawdowns() -> None:
    run = SimpleNamespace(
        trades=(),
        state=SimpleNamespace(
            wallet_balance=Decimal("100"),
            equity=Decimal("100"),
            positions=(),
        ),
        path_result=SimpleNamespace(
            path_state=SimpleNamespace(value="VALID"),
            invalid_reason=None,
            halt_trigger_time_utc_ms=None,
            final_processed_time_utc_ms=172_800_000,
        ),
        path_kind=SimpleNamespace(value="BASELINE"),
        daily_equity_points=(
            SimpleNamespace(event_time_utc_ms=86_400_000, equity=Decimal("110")),
            SimpleNamespace(event_time_utc_ms=172_800_000, equity=Decimal("100")),
        ),
        engine_peak_observed_drawdown=Decimal("0.2"),
        planning_outputs=(),
        processed_minute_count=2,
    )

    metric = summarize_path(
        run,
        initial_capital=Decimal("100"),
        split_start_utc_ms=0,
        split_end_utc_ms=172_799_999,
        slippage_rates={},
    )

    assert metric["daily_close_max_drawdown"] == "0.0909090909090909"
    assert metric["engine_peak_observed_drawdown"] == "0.2"
    assert "maximum_drawdown" not in metric


def test_economic_total_cost_subtracts_funding_cashflow() -> None:
    assert economic_total_cost(
        fees=Decimal("150.775458120"),
        slippage=Decimal("40.57374866602492077111457400"),
        funding_cashflow=Decimal("-24.7758397568927621730"),
    ) == Decimal("216.125046542918")
