from __future__ import annotations

import math
import random
from collections import Counter
from decimal import Decimal
from itertools import pairwise
from statistics import mean, pstdev

from pa_agent.research_backtest.domain.rejections import ExecutionRejection
from pa_agent.research_backtest.simulation.ledger import LedgerKind


def _ratio(value: Decimal, denominator: Decimal) -> str | None:
    return str(value / denominator) if denominator else None


def summarize_path(
    run: object,
    *,
    initial_capital: Decimal,
    split_start_utc_ms: int,
    split_end_utc_ms: int,
    slippage_rates: dict[str, Decimal],
) -> dict[str, object]:
    trades = run.trades
    final = run.state.wallet_balance if not run.state.positions else run.state.equity
    net_return = (final - initial_capital) / initial_capital
    days = max((run.path_result.final_processed_time_utc_ms - split_start_utc_ms) / 86_400_000, 1)
    annualized = (float(final / initial_capital) ** (365.25 / days) - 1) if final > 0 else -1.0
    equities = [initial_capital, *(item.equity for item in run.daily_equity_points), final]
    peak = equities[0]
    max_drawdown = Decimal("0")
    dd_start = split_start_utc_ms
    dd_end = split_start_utc_ms
    peak_time = split_start_utc_ms
    points = [
        (split_start_utc_ms, initial_capital),
        *((item.event_time_utc_ms, item.equity) for item in run.daily_equity_points),
        (run.path_result.final_processed_time_utc_ms, final),
    ]
    for time, equity in points:
        if equity > peak:
            peak, peak_time = equity, time
        drawdown = (peak - equity) / peak if peak else Decimal("0")
        if drawdown > max_drawdown:
            max_drawdown, dd_start, dd_end = drawdown, peak_time, time
    daily_returns = [float(right / left - 1) for left, right in pairwise(equities) if left != 0]
    volatility = pstdev(daily_returns) if len(daily_returns) > 1 else 0.0
    downside = [min(value, 0.0) for value in daily_returns]
    downside_dev = math.sqrt(mean(value * value for value in downside)) if downside else 0.0
    sharpe = mean(daily_returns) / volatility * math.sqrt(365.25) if volatility else None
    sortino = mean(daily_returns) / downside_dev * math.sqrt(365.25) if downside_dev else None
    calmar = annualized / float(max_drawdown) if max_drawdown else None
    wins = [item.net_pnl for item in trades if item.net_pnl > 0]
    losses = [item.net_pnl for item in trades if item.net_pnl < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = -sum(losses, Decimal("0"))
    fees = sum((item.entry_fee + item.exit_fee for item in trades), Decimal("0"))
    funding = sum((item.funding for item in trades), Decimal("0"))
    slippage = Decimal("0")
    for item in trades:
        rate = slippage_rates[item.symbol]
        entry_base = item.entry_price / (
            Decimal("1") + rate if item.side.value == "LONG" else Decimal("1") - rate
        )
        exit_base = item.exit_price / (
            Decimal("1") - rate if item.side.value == "LONG" else Decimal("1") + rate
        )
        slippage += item.quantity * (
            abs(item.entry_price - entry_base) + abs(item.exit_price - exit_base)
        )
    rejections = Counter(
        item.reason.value for item in run.planning_outputs if isinstance(item, ExecutionRejection)
    )
    symbol_counts = Counter(item.symbol for item in trades)
    side_counts = Counter(item.side.value for item in trades)
    holding = [item.exit_time_utc_ms - item.entry_time_utc_ms for item in trades]
    annualization_reason = None
    if run.path_result.path_state.value == "INVALID":
        annualization_reason = "PATH_INVALID_METRICS_END_AT_INVALIDATION"
    elif run.path_result.path_state.value == "HALTED":
        annualization_reason = "PATH_HALTED_METRICS_END_AT_FLAT_AFTER_HALT"
    return {
        "path_kind": run.path_kind.value,
        "path_state": run.path_result.path_state.value,
        "invalid_reason": run.path_result.invalid_reason,
        "halt_trigger_time_utc_ms": run.path_result.halt_trigger_time_utc_ms,
        "initial_capital": str(initial_capital),
        "final_capital": str(final),
        "net_return": str(net_return),
        "annualized_return": annualized,
        "annualization_qualification": annualization_reason,
        "maximum_drawdown": str(max_drawdown),
        "maximum_drawdown_start_utc_ms": dd_start,
        "maximum_drawdown_end_utc_ms": dd_end,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "trade_count": len(trades),
        "symbol_trade_counts": dict(sorted(symbol_counts.items())),
        "side_trade_counts": dict(sorted(side_counts.items())),
        "win_rate": _ratio(Decimal(len(wins)), Decimal(len(trades))),
        "profit_factor": _ratio(gross_profit, gross_loss),
        "average_payoff_ratio": _ratio(
            gross_profit / len(wins) if wins else Decimal("0"),
            gross_loss / len(losses) if losses else Decimal("0"),
        ),
        "average_holding_minutes": (sum(holding) / len(holding) / 60_000 if holding else None),
        "fees": str(fees),
        "slippage": str(slippage),
        "funding": str(funding),
        "total_cost": str(fees + slippage + funding),
        "execution_rejections": dict(sorted(rejections.items())),
        "processed_minute_count": run.processed_minute_count,
        "split_end_utc_ms": split_end_utc_ms,
    }


def ledger_cost_totals(run: object) -> dict[str, str]:
    totals = Counter()
    for item in run.ledger_entries:
        if item.kind in {LedgerKind.ENTRY_FEE, LedgerKind.EXIT_FEE, LedgerKind.FUNDING}:
            totals[item.kind.value] += -item.wallet_delta
    return {name: str(value) for name, value in sorted(totals.items())}


def moving_block_bootstrap_ci(
    values: list[float], *, block_size: int, statistic, samples: int = 10_000
) -> dict[str, object]:
    if not values or len(values) < block_size:
        return {"status": "UNDEFINED", "reason": "INSUFFICIENT_OBSERVATIONS"}
    rng = random.Random(20_260_713)
    starts = range(0, len(values) - block_size + 1)
    estimates = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < len(values):
            start = rng.choice(starts)
            sample.extend(values[start : start + block_size])
        estimate = statistic(sample[: len(values)])
        if estimate is not None and math.isfinite(estimate):
            estimates.append(estimate)
    if len(estimates) != samples:
        return {"status": "UNDEFINED", "reason": "STATISTIC_DENOMINATOR_ZERO"}
    estimates.sort()
    return {
        "status": "DEFINED",
        "lower_95": estimates[int(samples * 0.025)],
        "upper_95": estimates[int(samples * 0.975) - 1],
        "samples": samples,
        "seed": 20_260_713,
        "block_size": block_size,
    }


def oos_confidence_intervals(run: object, initial_capital: Decimal) -> dict[str, object]:
    equities = [float(initial_capital), *(float(item.equity) for item in run.daily_equity_points)]
    daily = [right / left - 1 for left, right in pairwise(equities) if left]
    trade_pnl = [float(item.net_pnl) for item in run.trades]

    def profit_factor(values: list[float]) -> float | None:
        gains = sum(value for value in values if value > 0)
        losses = -sum(value for value in values if value < 0)
        return gains / losses if losses else None

    return {
        "daily_net_return": moving_block_bootstrap_ci(daily, block_size=7, statistic=mean),
        "profit_factor": moving_block_bootstrap_ci(
            trade_pnl, block_size=5, statistic=profit_factor
        ),
    }
