from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import statistics
import zipfile
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from pa_agent.research_2d.data import load_strategy_bars
from pa_agent.research_2d.metrics import economic_total_cost
from pa_agent.research_2d.runner import BASE_SLIPPAGE, Split, _load_candidates
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.ema import ema
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig

ATTRIBUTION_VERSION = "V1_FAILURE_ATTRIBUTION_V1"
POST_HOC = "POST_HOC_DIAGNOSTIC_ONLY"
INPUT_MISMATCH = "ATTRIBUTION_INPUT_MISMATCH"
STRATEGY_INPUT_FIELDS = frozenset(
    {
        "daily_close",
        "EMA50",
        "EMA200",
        "daily_trend_strength",
        "4H_ATR",
        "ATR_percent_of_price",
        "Donchian_upper",
        "Donchian_lower",
        "breakout_distance",
        "breakout_strength",
        "prior_20_bar_range_over_ATR",
    }
)
POST_EXIT_DIAGNOSTIC_FIELDS = frozenset(
    {
        "post_exit_4h_directional_return",
        "post_exit_12h_directional_return",
        "post_exit_24h_directional_return",
        "continued_first_touch",
        "classification",
    }
)
EXPECTED_EXPERIMENT_ID = "309437824a0abb1611d470d07f91eb1ad69c235dc22027e405fdc89b4b816500"
EXPECTED_TRADE_COUNT = 169
TRAINING_START_UTC_MS = 1_601_510_400_000
DEPENDENCY_LOCK_HASH = "49fbf4f88089a8228fde1afb7cb1c5b8d08f230324998b43061c51889d6504d6"


class AttributionInputMismatch(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value))


def _utc(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _decimal_sum(values: Any) -> Decimal:
    return sum((Decimal(str(value)) for value in values), Decimal("0"))


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator else None


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _verify_bound_files(root: Path, manifest_name: str = "result_manifest.json") -> dict[str, Any]:
    manifest_path = root / manifest_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    for name, expected in sorted(manifest["file_sha256"].items()):
        path = root / name
        actual = _sha256_file(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({"path": str(path), "expected": expected, "actual": actual})
    if mismatches:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: {mismatches}")
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha256_file(manifest_path),
        "verified_file_count": len(manifest["file_sha256"]),
        "manifest": manifest,
    }


def _verify_archive(archive_root: Path) -> dict[str, Any]:
    manifest_path = archive_root / "archive_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    for name, expected in sorted(manifest["file_sha256"].items()):
        path = archive_root / name
        actual = _sha256_file(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({"path": str(path), "expected": expected, "actual": actual})
    report = json.loads((archive_root / "archival_report.json").read_text(encoding="utf-8"))
    if (
        report["source_experiment_id"] != EXPECTED_EXPERIMENT_ID
        or report["final_conclusion"] != "STRATEGY_FAILED_BASELINE_VALIDATION"
    ):
        mismatches.append({"path": "archival_report.json", "reason": "identity/conclusion"})
    if mismatches:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: {mismatches}")
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha256_file(manifest_path),
        "verified_file_count": len(manifest["file_sha256"]),
        "report": report,
    }


def _month_keys(start_ms: int, end_ms: int) -> set[str]:
    start = datetime.fromtimestamp(start_ms / 1000, tz=UTC)
    current = datetime(start.year, start.month, 1, tzinfo=UTC)
    end = datetime.fromtimestamp(end_ms / 1000, tz=UTC)
    keys = set()
    while (current.year, current.month) <= (end.year, end.month):
        keys.add(f"{current.year:04d}-{current.month:02d}")
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return keys


def _verify_data_shards(data_root: Path, *, oos_start: int, oos_end: int) -> dict[str, Any]:
    manifest_path = data_root / "archive_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    oos_months = _month_keys(oos_start, oos_end)
    feature_months = _month_keys(1_577_836_800_000, oos_end)
    selected = []
    for item in manifest["shards"]:
        stream = item["stream_name"]
        month = item["month"]
        required = (stream in {"trade_1m", "mark_1m", "funding"} and month in oos_months) or (
            stream in {"trade_4h", "trade_1d"} and month in feature_months
        )
        if required:
            selected.append(item)
    expected_count = 2 * (len(oos_months) * 3 + len(feature_months) * 2)
    if len(selected) != expected_count:
        raise AttributionInputMismatch(
            f"{INPUT_MISMATCH}: expected {expected_count} data shards, found {len(selected)}"
        )
    records = []
    for item in sorted(selected, key=lambda row: (row["symbol"], row["stream_name"], row["month"])):
        path = Path(item["canonical_path"])
        actual = _sha256_file(path) if path.is_file() else None
        expected = item["canonical_content_hash"]
        if actual != expected:
            raise AttributionInputMismatch(
                f"{INPUT_MISMATCH}: {path}: expected {expected}, actual {actual}"
            )
        records.append(
            {
                "symbol": item["symbol"],
                "stream": item["stream_name"],
                "month": item["month"],
                "path": str(path.resolve()),
                "sha256": actual,
            }
        )
    return {
        "archive_manifest_path": str(manifest_path.resolve()),
        "archive_manifest_sha256": _sha256_file(manifest_path),
        "verified_shard_count": len(records),
        "verified_shards": records,
    }


def _load_path_values(path: Path, path_kind: str) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["path_kind"] == path_kind:
                rows.append(item["value"])
    return rows


def _verify_path_equality(core_root: Path) -> dict[str, list[dict[str, Any]]]:
    output = {}
    for name in (
        "trades.jsonl",
        "fills.jsonl",
        "planning.jsonl",
        "ledger.jsonl",
        "equity_daily.jsonl",
    ):
        baseline = _load_path_values(core_root / name, "BASELINE")
        conservative = _load_path_values(core_root / name, "CONSERVATIVE")
        baseline_economic = [
            {key: value for key, value in row.items() if key != "path_kind"} for row in baseline
        ]
        conservative_economic = [
            {key: value for key, value in row.items() if key != "path_kind"} for row in conservative
        ]
        if baseline_economic != conservative_economic:
            raise AttributionInputMismatch(f"{INPUT_MISMATCH}: path mismatch in {name}")
        output[name] = baseline
    return output


def _trade_id(trade: dict[str, Any]) -> str:
    return f"trade_{canonical_sha256(trade)[:24]}"


def calculate_slippage_cost(trade: dict[str, Any]) -> Decimal:
    rate = BASE_SLIPPAGE[trade["symbol"]]
    entry = Decimal(trade["entry_price"])
    exit_price = Decimal(trade["exit_price"])
    quantity = Decimal(trade["quantity"])
    if trade["side"] == "LONG":
        entry_base = entry / (Decimal("1") + rate)
        exit_base = exit_price / (Decimal("1") - rate)
    else:
        entry_base = entry / (Decimal("1") - rate)
        exit_base = exit_price / (Decimal("1") + rate)
    return quantity * (abs(entry - entry_base) + abs(exit_price - exit_base))


def planned_reward_values(plan: dict[str, Any]) -> dict[str, Decimal]:
    quantity = Decimal(plan["quantity"])
    entry = Decimal(plan["expected_entry_fill_price"])
    target = Decimal(plan["expected_take_profit_fill_price"])
    direction = Decimal("1") if plan["side"] == "LONG" else Decimal("-1")
    gross_reward = direction * (target - entry) * quantity
    reserved_cost = (
        Decimal(plan["entry_fee"])
        + Decimal(plan["exit_fee_reserve"])
        + Decimal(plan["funding_reserve"])
    )
    risk = Decimal(plan["planned_risk"])
    return {
        "planned_gross_reward_usdt": gross_reward,
        "estimated_round_trip_cost": reserved_cost,
        "planned_gross_reward_risk_ratio": gross_reward / risk,
        "planned_net_reward_risk_ratio": (gross_reward - reserved_cost) / risk,
    }


def calculate_excursions(
    *,
    side: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    initial_risk: Decimal,
    entry_time: int,
    exit_time: int,
    trade_rows: list[dict[str, Any]],
    mark_times: set[int],
    target_price: Decimal,
    include_exit_bar_extremes: bool,
) -> dict[str, Any]:
    expected_times = set(range(entry_time, exit_time + 1, 60_000))
    observed_trade_times = {int(row["open_time_utc_ms"]) for row in trade_rows}
    if expected_times - observed_trade_times or expected_times - mark_times:
        return {"availability": "MFE_MAE_UNAVAILABLE"}
    holding_rows = [
        row
        for row in trade_rows
        if int(row["open_time_utc_ms"]) < exit_time
        or (include_exit_bar_extremes and int(row["open_time_utc_ms"]) == exit_time)
    ]
    if not holding_rows:
        return {"availability": "MFE_MAE_UNAVAILABLE"}
    if side == "LONG":
        favorable = [(Decimal(row["high"]), int(row["open_time_utc_ms"])) for row in holding_rows]
        adverse = [(Decimal(row["low"]), int(row["open_time_utc_ms"])) for row in holding_rows]
        favorable.append((exit_price, exit_time))
        adverse.append((exit_price, exit_time))
        mfe_price, mfe_time = max(favorable, key=lambda item: (item[0], -item[1]))
        mae_price, mae_time = min(adverse, key=lambda item: (item[0], item[1]))
        mfe_distance = max(mfe_price - entry_price, Decimal("0"))
        mae_distance = max(entry_price - mae_price, Decimal("0"))
        reached_target = mfe_price >= target_price
        recovered = any(
            int(row["open_time_utc_ms"]) > mae_time and Decimal(row["high"]) >= entry_price
            for row in holding_rows
        ) or (exit_time > mae_time and exit_price >= entry_price)
    else:
        favorable = [(Decimal(row["low"]), int(row["open_time_utc_ms"])) for row in holding_rows]
        adverse = [(Decimal(row["high"]), int(row["open_time_utc_ms"])) for row in holding_rows]
        favorable.append((exit_price, exit_time))
        adverse.append((exit_price, exit_time))
        mfe_price, mfe_time = min(favorable, key=lambda item: (item[0], item[1]))
        mae_price, mae_time = max(adverse, key=lambda item: (item[0], -item[1]))
        mfe_distance = max(entry_price - mfe_price, Decimal("0"))
        mae_distance = max(mae_price - entry_price, Decimal("0"))
        reached_target = mfe_price <= target_price
        recovered = any(
            int(row["open_time_utc_ms"]) > mae_time and Decimal(row["low"]) <= entry_price
            for row in holding_rows
        ) or (exit_time > mae_time and exit_price <= entry_price)
    mfe_usdt = mfe_distance * quantity
    mae_usdt = mae_distance * quantity
    mfe_r = mfe_usdt / initial_risk
    mae_r = mae_usdt / initial_risk
    return {
        "availability": "AVAILABLE",
        "MFE_price": str(mfe_price),
        "MAE_price": str(mae_price),
        "MFE_usdt": str(mfe_usdt),
        "MAE_usdt": str(mae_usdt),
        "MFE_R": str(mfe_r),
        "MAE_R": str(mae_r),
        "time_to_MFE_minutes": (mfe_time - entry_time) // 60_000,
        "time_to_MAE_minutes": (mae_time - entry_time) // 60_000,
        "whether_reached_0_5R": mfe_r >= Decimal("0.5"),
        "whether_reached_1R": mfe_r >= Decimal("1"),
        "whether_reached_2R": mfe_r >= Decimal("2"),
        "whether_reached_target": reached_target,
        "whether_price_recovered_after_MAE": recovered,
    }


def _month_sequence(start_ms: int, end_ms: int) -> list[str]:
    return sorted(_month_keys(start_ms, end_ms))


@lru_cache(maxsize=16)
def _load_month(path_text: str) -> tuple[dict[str, Any], ...]:
    path = Path(path_text)
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def _interval_rows(
    data_root: Path, symbol: str, stream: str, start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    rows = []
    for month in _month_sequence(start_ms, end_ms):
        path = data_root / "data" / "canonical" / symbol / stream / f"{month}.jsonl"
        for row in _load_month(str(path.resolve())):
            key = "funding_time_utc_ms" if stream == "funding" else "open_time_utc_ms"
            time = int(row[key])
            if start_ms <= time <= end_ms:
                rows.append(row)
    return rows


def _regime(value: Decimal, low: Decimal, high: Decimal) -> str:
    if value < low:
        return "LOW"
    if value < high:
        return "MEDIUM"
    return "HIGH"


def _candidate_features(
    *, data_root: Path, candidates: tuple[object, ...], oos_end: int
) -> dict[str, dict[str, Any]]:
    result = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        bars = load_strategy_bars(
            data_root,
            symbol=symbol,
            authority="NATIVE_PRIMARY",
            start_utc_ms=1_577_836_800_000,
            end_utc_ms=oos_end,
        )
        daily_times = [bar.close_time_utc_ms for bar in bars.daily]
        daily_atr = wilder_atr(
            [bar.high for bar in bars.daily],
            [bar.low for bar in bars.daily],
            [bar.close for bar in bars.daily],
            14,
        )
        four_by_close = {bar.close_time_utc_ms: index for index, bar in enumerate(bars.four_hour)}
        for candidate in (item for item in candidates if item.symbol == symbol):
            index = four_by_close[candidate.decision_time_utc_ms]
            daily_index = bisect_right(daily_times, candidate.decision_time_utc_ms) - 1
            daily_atr_value = float64_to_decimal_15sig(daily_atr[daily_index])
            previous = bars.four_hour[index - 20 : index]
            prior_range = max(bar.high for bar in previous) - min(bar.low for bar in previous)
            if candidate.market_view.value == "LONG":
                breakout_distance = candidate.decision_close - candidate.donchian_high_previous_20
            else:
                breakout_distance = candidate.donchian_low_previous_20 - candidate.decision_close
            trend_strength = abs(candidate.ema50_daily - candidate.ema200_daily) / daily_atr_value
            atr_percent = candidate.atr14_4h / candidate.decision_close
            breakout_strength = breakout_distance / candidate.atr14_4h
            result[candidate.candidate_id] = {
                "daily_close": str(candidate.daily_close),
                "EMA50": str(candidate.ema50_daily),
                "EMA200": str(candidate.ema200_daily),
                "daily_ATR": str(daily_atr_value),
                "daily_trend_strength": str(trend_strength),
                "4H_ATR": str(candidate.atr14_4h),
                "ATR_percent_of_price": str(atr_percent),
                "Donchian_upper": str(candidate.donchian_high_previous_20),
                "Donchian_lower": str(candidate.donchian_low_previous_20),
                "breakout_distance": str(breakout_distance),
                "breakout_strength": str(breakout_strength),
                "prior_20_bar_range_over_ATR": str(prior_range / candidate.atr14_4h),
                "volatility_regime": _regime(atr_percent, Decimal("0.01"), Decimal("0.02")),
                "trend_regime": _regime(trend_strength, Decimal("1"), Decimal("2")),
                "breakout_regime": _regime(breakout_strength, Decimal("0.10"), Decimal("0.30")),
            }
    return result


def _trade_rows(
    *,
    core_rows: dict[str, list[dict[str, Any]]],
    candidates: tuple[object, ...],
    data_root: Path,
    oos_end: int,
) -> list[dict[str, Any]]:
    trades = core_rows["trades.jsonl"]
    plans = {
        row["candidate_id"]: row
        for row in core_rows["planning.jsonl"]
        if row.get("schema_version") == "ENTRY_EXECUTION_PLAN_SCHEMA_V1"
    }
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    exit_fill_by_position = {
        row["position_id"]: row for row in core_rows["fills.jsonl"] if row["action"] == "EXIT"
    }
    features = _candidate_features(data_root=data_root, candidates=candidates, oos_end=oos_end)
    rows = []
    for trade in trades:
        candidate_id = trade["origin_candidate_id"]
        plan = plans[candidate_id]
        candidate = candidate_map[candidate_id]
        entry_time = int(trade["entry_time_utc_ms"])
        exit_time = int(trade["exit_time_utc_ms"])
        market_rows = _interval_rows(data_root, trade["symbol"], "trade_1m", entry_time, exit_time)
        mark_rows = _interval_rows(data_root, trade["symbol"], "mark_1m", entry_time, exit_time)
        risk = Decimal(plan["planned_risk"])
        reward = planned_reward_values(plan)
        fee = Decimal(trade["entry_fee"]) + Decimal(trade["exit_fee"])
        slippage = calculate_slippage_cost(trade)
        funding = Decimal(trade["funding"])
        net_pnl = Decimal(trade["net_pnl"])
        exit_fill = exit_fill_by_position[trade["position_id"]]
        if trade["exit_reason"] == "TIME_EXIT":
            protective_outcome = "TIME_EXIT"
        elif "TAKE_PROFIT" in exit_fill["plan_id"]:
            protective_outcome = "TARGET"
        elif exit_fill["plan_id"].endswith(":STOP"):
            protective_outcome = "STOP"
        else:
            raise AttributionInputMismatch(
                f"{INPUT_MISMATCH}: unknown protective exit {exit_fill['plan_id']}"
            )
        excursions = calculate_excursions(
            side=trade["side"],
            entry_price=Decimal(trade["entry_price"]),
            exit_price=Decimal(trade["exit_price"]),
            quantity=Decimal(trade["quantity"]),
            initial_risk=risk,
            entry_time=entry_time,
            exit_time=exit_time,
            trade_rows=market_rows,
            mark_times={int(item["open_time_utc_ms"]) for item in mark_rows},
            target_price=Decimal(plan["take_profit_trigger_price"]),
            include_exit_bar_extremes=trade["exit_reason"] == "PROTECTIVE",
        )
        row = {
            "trade_id": _trade_id(trade),
            "candidate_id": candidate_id,
            "plan_id": trade["origin_plan_id"],
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entry_time": _utc(entry_time),
            "exit_time": _utc(exit_time),
            "entry_time_utc_ms": entry_time,
            "exit_time_utc_ms": exit_time,
            "exit_reason": trade["exit_reason"],
            "protective_outcome": protective_outcome,
            "entry_price": trade["entry_price"],
            "exit_price": trade["exit_price"],
            "quantity": trade["quantity"],
            "gross_pnl": trade["gross_pnl"],
            "fee": str(fee),
            "slippage_cost": str(slippage),
            "funding_cashflow": str(funding),
            "economic_cost": str(fee + slippage - funding),
            "net_pnl": trade["net_pnl"],
            "holding_minutes": (exit_time - entry_time) // 60_000,
            "realized_R_multiple": str(net_pnl / risk),
            "planned_stop_price": plan["stop_trigger_price"],
            "planned_target_price": plan["take_profit_trigger_price"],
            "initial_risk_usdt": plan["planned_risk"],
            "planned_gross_reward_usdt": str(reward["planned_gross_reward_usdt"]),
            "estimated_round_trip_cost": str(reward["estimated_round_trip_cost"]),
            "estimated_funding_reserve": plan["funding_reserve"],
            "planned_gross_reward_risk_ratio": str(reward["planned_gross_reward_risk_ratio"]),
            "planned_net_reward_risk_ratio": str(reward["planned_net_reward_risk_ratio"]),
            "candidate_decision_time_utc_ms": candidate.decision_time_utc_ms,
            "entry_trend_state": candidate.trend_state.value,
            **features[candidate_id],
            **excursions,
        }
        rows.append(row)
    return rows


def _profit_factor(rows: list[dict[str, Any]]) -> Decimal | None:
    profit = _decimal_sum(row["net_pnl"] for row in rows if Decimal(row["net_pnl"]) > 0)
    loss = -_decimal_sum(row["net_pnl"] for row in rows if Decimal(row["net_pnl"]) < 0)
    return _safe_ratio(profit, loss)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [Decimal(row["realized_R_multiple"]) for row in rows]
    available = [row for row in rows if row["availability"] == "AVAILABLE"]
    gross_profit = _decimal_sum(row["net_pnl"] for row in rows if Decimal(row["net_pnl"]) > 0)
    costs = _decimal_sum(row["economic_cost"] for row in rows)
    return {
        "trade_count": len(rows),
        "net_pnl": str(_decimal_sum(row["net_pnl"] for row in rows)),
        "gross_pnl": str(_decimal_sum(row["gross_pnl"] for row in rows)),
        "win_rate": str(Decimal(sum(Decimal(row["net_pnl"]) > 0 for row in rows)) / len(rows))
        if rows
        else None,
        "profit_factor": _decimal_text(_profit_factor(rows)),
        "average_R": str(sum(realized, Decimal("0")) / len(realized)) if realized else None,
        "median_R": str(statistics.median(realized)) if realized else None,
        "average_MFE_R": str(_decimal_sum(row["MFE_R"] for row in available) / len(available))
        if available
        else None,
        "average_MAE_R": str(_decimal_sum(row["MAE_R"] for row in available) / len(available))
        if available
        else None,
        "total_cost": str(costs),
        "cost_to_gross_profit": _decimal_text(_safe_ratio(costs, gross_profit)),
        "sample_quality": "SUFFICIENT" if len(rows) >= 30 else "INSUFFICIENT_SUBGROUP_SAMPLE",
    }


def _bin_planned_net_r(value: Decimal) -> str:
    if value < 1:
        return "LT_1R"
    if value < Decimal("1.5"):
        return "1_TO_1_5R"
    if value < 2:
        return "1_5_TO_2R"
    return "GE_2R"


def _holding_bin(value: int) -> str:
    if value < 720:
        return "LT_12H"
    if value < 1_440:
        return "12_TO_24H"
    if value < 2_880:
        return "24_TO_48H"
    return "GE_48H"


def subgroup_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions = {
        "symbol": lambda row: row["symbol"].replace("USDT", ""),
        "side": lambda row: row["side"],
        "exit_reason": lambda row: row["protective_outcome"],
        "trend_regime": lambda row: row["trend_regime"],
        "volatility_regime": lambda row: row["volatility_regime"],
        "breakout_regime": lambda row: row["breakout_regime"],
        "planned_net_R": lambda row: _bin_planned_net_r(
            Decimal(row["planned_net_reward_risk_ratio"])
        ),
        "holding_duration": lambda row: _holding_bin(int(row["holding_minutes"])),
        "month": lambda row: row["entry_time"][:7],
        "year": lambda row: row["entry_time"][:4],
    }
    output = {"schema_version": ATTRIBUTION_VERSION, "total_trade_count": len(rows), "groups": {}}
    for dimension, classifier in dimensions.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[classifier(row)].append(row)
        output["groups"][dimension] = {
            key: _summarize(group) for key, group in sorted(grouped.items())
        }
    return output


@lru_cache(maxsize=4)
def _exit_trend_series(
    data_root_text: str, symbol: str
) -> tuple[
    tuple[int, ...], tuple[Decimal, ...], tuple[Decimal | None, ...], tuple[Decimal | None, ...]
]:
    bars = load_strategy_bars(
        Path(data_root_text),
        symbol=symbol,
        authority="NATIVE_PRIMARY",
        start_utc_ms=1_577_836_800_000,
        end_utc_ms=1_800_000_000_000,
    )
    closes = tuple(bar.close for bar in bars.daily)
    return (
        tuple(bar.close_time_utc_ms for bar in bars.daily),
        closes,
        tuple(
            float64_to_decimal_15sig(value) if value is not None else None
            for value in ema(closes, 50)
        ),
        tuple(
            float64_to_decimal_15sig(value) if value is not None else None
            for value in ema(closes, 200)
        ),
    )


def _trend_invalidated_at_exit(
    *, data_root: Path, symbol: str, side: str, exit_time: int
) -> tuple[bool | None, str | None, int]:
    # V1 daily trend evidence is evaluated at each fully closed 4H decision boundary.
    latest_complete_four_hour = exit_time // 14_400_000 * 14_400_000 - 1
    times, closes, ema50_values, ema200_values = _exit_trend_series(
        str(data_root.resolve()), symbol
    )
    index = bisect_right(times, latest_complete_four_hour) - 1
    if index < 0 or ema50_values[index] is None or ema200_values[index] is None:
        return None, None, latest_complete_four_hour
    if closes[index] > ema200_values[index] and ema50_values[index] > ema200_values[index]:
        trend = "BULL"
    elif closes[index] < ema200_values[index] and ema50_values[index] < ema200_values[index]:
        trend = "BEAR"
    else:
        trend = "NEUTRAL"
    expected = "BULL" if side == "LONG" else "BEAR"
    return trend != expected, trend, latest_complete_four_hour


def _future_analysis(row: dict[str, Any], data_root: Path) -> dict[str, Any]:
    exit_time = int(row["exit_time_utc_ms"])
    future = _interval_rows(
        data_root, row["symbol"], "trade_1m", exit_time + 60_000, exit_time + 86_400_000
    )
    by_time = {int(item["open_time_utc_ms"]): item for item in future}
    exit_price = Decimal(row["exit_price"])
    direction = Decimal("1") if row["side"] == "LONG" else Decimal("-1")
    changes = {}
    for hours in (4, 12, 24):
        target = exit_time + hours * 3_600_000
        price = Decimal(by_time[target]["open"]) if target in by_time else None
        changes[f"post_exit_{hours}h_directional_return"] = (
            str(direction * (price / exit_price - 1)) if price is not None else None
        )
    stop = Decimal(row["planned_stop_price"])
    target = Decimal(row["planned_target_price"])
    first_stop = first_target = None
    for item in future:
        time = int(item["open_time_utc_ms"])
        if row["side"] == "LONG":
            stop_hit, target_hit = Decimal(item["low"]) <= stop, Decimal(item["high"]) >= target
        else:
            stop_hit, target_hit = Decimal(item["high"]) >= stop, Decimal(item["low"]) <= target
        if stop_hit and first_stop is None:
            first_stop = time
        if target_hit and first_target is None:
            first_target = time
    trend_invalidated, exit_trend, trend_decision_time = _trend_invalidated_at_exit(
        data_root=data_root,
        symbol=row["symbol"],
        side=row["side"],
        exit_time=exit_time,
    )
    if first_target is not None and (first_stop is None or first_target < first_stop):
        classification = "EXIT_TOO_EARLY"
    elif row["whether_reached_0_5R"] and Decimal(row["net_pnl"]) <= 0:
        classification = "GAVE_BACK_PROFIT"
    elif first_stop is not None and (first_target is None or first_stop < first_target):
        classification = "LOSS_LIMITING"
    elif not row["whether_reached_0_5R"]:
        classification = "NO_FOLLOW_THROUGH"
    else:
        classification = "INCONCLUSIVE"
    return {
        **changes,
        "continued_first_touch": "TARGET"
        if first_target is not None and (first_stop is None or first_target < first_stop)
        else (
            "STOP"
            if first_stop is not None and (first_target is None or first_stop < first_target)
            else "NONE_OR_AMBIGUOUS"
        ),
        "classification": classification,
        "nearest_complete_4h_decision_time": _utc(trend_decision_time),
        "nearest_complete_4h_daily_trend_state": exit_trend,
        "nearest_complete_4h_trend_invalidated": trend_invalidated,
        "analysis_scope": POST_HOC,
    }


def time_exit_analysis(rows: list[dict[str, Any]], data_root: Path) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        if row["exit_reason"] != "TIME_EXIT":
            continue
        mfe = Decimal(row["MFE_usdt"]) if row["availability"] == "AVAILABLE" else None
        net = Decimal(row["net_pnl"])
        output.append(
            {
                "trade_id": row["trade_id"],
                "symbol": row["symbol"],
                "side": row["side"],
                "exit_time": row["exit_time"],
                "exit_floating_state": "PROFIT" if net > 0 else ("LOSS" if net < 0 else "FLAT"),
                "pre_exit_MFE_R": row.get("MFE_R"),
                "reached_0_5R": row.get("whether_reached_0_5R"),
                "reached_1R": row.get("whether_reached_1R"),
                "reached_2R": row.get("whether_reached_2R"),
                "giveback_from_MFE_usdt": str(mfe - net) if mfe is not None else None,
                **_future_analysis(row, data_root),
            }
        )
    return output


def cost_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fees = _decimal_sum(row["fee"] for row in rows)
    slippage = _decimal_sum(row["slippage_cost"] for row in rows)
    funding_income = _decimal_sum(
        row["funding_cashflow"] for row in rows if Decimal(row["funding_cashflow"]) > 0
    )
    funding_expense = -_decimal_sum(
        row["funding_cashflow"] for row in rows if Decimal(row["funding_cashflow"]) < 0
    )
    funding_cashflow = funding_income - funding_expense
    gross_profit = _decimal_sum(row["net_pnl"] for row in rows if Decimal(row["net_pnl"]) > 0)
    gross_loss = -_decimal_sum(row["net_pnl"] for row in rows if Decimal(row["net_pnl"]) < 0)
    insufficient = sum(
        row["availability"] == "AVAILABLE"
        and Decimal(row["MFE_usdt"]) < Decimal(row["economic_cost"])
        for row in rows
    )
    flips = sum(
        Decimal(row["net_pnl"]) < 0 and Decimal(row["net_pnl"]) + Decimal(row["economic_cost"]) > 0
        for row in rows
    )
    total_net = _decimal_sum(row["net_pnl"] for row in rows)
    total_risk = _decimal_sum(row["initial_risk_usdt"] for row in rows)
    mean_realized_r = _decimal_sum(row["realized_R_multiple"] for row in rows) / len(rows)
    losses_sorted = sorted(Decimal(row["net_pnl"]) for row in rows if Decimal(row["net_pnl"]) < 0)
    removed = Decimal("0")
    remove_count = 0
    for loss in losses_sorted:
        removed -= loss
        remove_count += 1
        if total_net + removed >= 0:
            break
    return {
        "schema_version": ATTRIBUTION_VERSION,
        "gross_profit_of_net_winners": str(gross_profit),
        "gross_loss_of_net_losers": str(gross_loss),
        "fees": str(fees),
        "slippage": str(slippage),
        "funding_income": str(funding_income),
        "funding_expense": str(funding_expense),
        "funding_cashflow": str(funding_cashflow),
        "economic_total_cost": str(
            economic_total_cost(fees=fees, slippage=slippage, funding_cashflow=funding_cashflow)
        ),
        "formula": "fees + slippage - funding_cashflow",
        "mfe_insufficient_to_cover_round_trip_cost_count": insufficient,
        "profitable_before_cost_but_loss_after_cost_count": flips,
        "additional_average_edge_usdt_per_trade_for_breakeven": str(-total_net / len(rows)),
        "additional_average_R_for_breakeven": str(-mean_realized_r),
        "risk_weighted_additional_R_for_breakeven": str(-total_net / total_risk),
        "post_hoc_minimum_worst_loss_trade_removal_count_for_breakeven": remove_count,
        "post_hoc_trade_removal_fraction_for_breakeven": str(Decimal(remove_count) / len(rows)),
        "post_hoc_warning": POST_HOC,
    }


def odds_analysis(rows: list[dict[str, Any]], subgroup: dict[str, Any]) -> dict[str, Any]:
    positive = sorted(
        (Decimal(row["net_pnl"]) for row in rows if Decimal(row["net_pnl"]) > 0), reverse=True
    )
    total_profit = sum(positive, Decimal("0"))
    cumulative = Decimal("0")
    count_80 = 0
    for value in positive:
        cumulative += value
        count_80 += 1
        if cumulative >= total_profit * Decimal("0.8"):
            break
    ranked = sorted(rows, key=lambda row: Decimal(row["net_pnl"]), reverse=True)
    removals = {}
    for count in (1, 3, 5):
        remaining = ranked[count:]
        removals[str(count)] = _summarize(remaining)
    bins = subgroup["groups"]["planned_net_R"]
    ordered_bins = sorted(
        bins.items(),
        key=lambda item: {"LT_1R": 0, "1_TO_1_5R": 1, "1_5_TO_2R": 2, "GE_2R": 3}[item[0]],
    )
    sufficient = [(name, value) for name, value in ordered_bins if value["trade_count"] >= 30]
    high_quality_signal = len(sufficient) >= 2 and Decimal(
        sufficient[-1][1]["profit_factor"] or "0"
    ) > Decimal(sufficient[0][1]["profit_factor"] or "0")
    available = [row for row in rows if row["availability"] == "AVAILABLE"]
    planned_net_values = [Decimal(row["planned_net_reward_risk_ratio"]) for row in rows]
    return {
        "schema_version": ATTRIBUTION_VERSION,
        "planned_net_R_bins": bins,
        "higher_planned_net_R_has_higher_expectation_in_sufficient_bins": high_quality_signal,
        "high_reward_ratio_may_reduce_target_hit_rate": True,
        "planned_net_R_discriminates_low_quality": high_quality_signal,
        "planned_net_R_minimum": str(min(planned_net_values)),
        "planned_net_R_maximum": str(max(planned_net_values)),
        "planned_net_R_conclusion": "NO_DISCRIMINATION_ALL_TRADES_BELOW_1R"
        if len(bins) == 1 and "LT_1R" in bins
        else "MIXED_BINS_AVAILABLE",
        "average_MFE_R": str(_decimal_sum(row["MFE_R"] for row in available) / len(available)),
        "average_MAE_R": str(_decimal_sum(row["MAE_R"] for row in available) / len(available)),
        "reached_0_5R_count": sum(row["whether_reached_0_5R"] for row in available),
        "reached_1R_count": sum(row["whether_reached_1R"] for row in available),
        "reached_2R_count": sum(row["whether_reached_2R"] for row in available),
        "reached_target_count": sum(row["whether_reached_target"] for row in available),
        "profitable_trade_count": len(positive),
        "trades_contributing_80_percent_of_gross_profit": count_80,
        "profit_concentration_fraction": str(Decimal(count_80) / len(positive))
        if positive
        else None,
        "performance_after_removing_best_trades": removals,
        "warning": POST_HOC,
    }


def hypothesis_assessment(
    rows: list[dict[str, Any]], subgroup: dict[str, Any], time_exits: list[dict[str, Any]]
) -> dict[str, Any]:
    base_pf = _profit_factor(rows) or Decimal("0")
    h1_groups = [
        subgroup["groups"]["trend_regime"].get("HIGH"),
        subgroup["groups"]["breakout_regime"].get("HIGH"),
    ]
    h1_support = [
        group
        for group in h1_groups
        if group and group["trade_count"] >= 30 and Decimal(group["profit_factor"] or "0") > base_pf
    ]
    h2_affected = sum(
        row["classification"] in {"EXIT_TOO_EARLY", "GAVE_BACK_PROFIT"} for row in time_exits
    )
    short_high = [row for row in rows if row["side"] == "SHORT" and row["trend_regime"] == "HIGH"]
    short_pf = _profit_factor([row for row in rows if row["side"] == "SHORT"]) or Decimal("0")
    short_high_pf = _profit_factor(short_high) or Decimal("0")
    h2_invalidated = sum(row["nearest_complete_4h_trend_invalidated"] is True for row in time_exits)
    assessments = {
        "H1": {
            "hypothesis": "COST_ADJUSTED_TREND_BREAKOUT_QUALITY_FILTER",
            "supporting_evidence": f"{len(h1_support)} sufficient high-quality groups exceed baseline PF",
            "contradicting_evidence": "Regime cuts are fixed diagnostics but still evaluated on the same OOS sample",
            "affected_trade_count": max((group["trade_count"] for group in h1_support), default=0),
            "sample_size_quality": "SUFFICIENT" if h1_support else "INSUFFICIENT",
            "look_ahead_risk": "MEDIUM",
            "estimated_complexity": "LOW",
            "overfitting_risk": "MEDIUM_HIGH",
            "recommendation": "SUPPORTED_FOR_LIMITED_V2_TEST"
            if h1_support
            else "INSUFFICIENT_EVIDENCE",
        },
        "H2": {
            "hypothesis": "TREND_INVALIDATION_EXIT_INSTEAD_OF_FIXED_TIME_EXIT",
            "supporting_evidence": f"{h2_affected} TIME_EXIT trades show exit-too-early or gave-back-profit diagnostics",
            "contradicting_evidence": f"Only {h2_invalidated} of {len(time_exits)} TIME_EXIT trades had the frozen daily trend invalidated at the latest complete 4H boundary; post-exit observations are non-causal",
            "affected_trade_count": h2_affected,
            "sample_size_quality": "SUFFICIENT" if h2_affected >= 30 else "INSUFFICIENT",
            "look_ahead_risk": "HIGH",
            "estimated_complexity": "MEDIUM",
            "overfitting_risk": "HIGH",
            "recommendation": "SUPPORTED_FOR_LIMITED_V2_TEST"
            if h2_affected >= 30 and h2_invalidated >= 30
            else "INSUFFICIENT_EVIDENCE",
        },
        "H3": {
            "hypothesis": "STRICTER_SHORT_TREND_AND_BREAKOUT_THRESHOLDS",
            "supporting_evidence": f"SHORT PF={short_pf}; high-trend SHORT PF={short_high_pf}",
            "contradicting_evidence": f"Only {len(short_high)} high-trend SHORT trades are available",
            "affected_trade_count": len(short_high),
            "sample_size_quality": "SUFFICIENT" if len(short_high) >= 30 else "INSUFFICIENT",
            "look_ahead_risk": "MEDIUM_HIGH",
            "estimated_complexity": "LOW",
            "overfitting_risk": "HIGH",
            "recommendation": (
                "SUPPORTED_FOR_LIMITED_V2_TEST"
                if len(short_high) >= 30 and short_high_pf > short_pf
                else (
                    "REJECTED_BY_V1_EVIDENCE"
                    if len(short_high) >= 30 and short_high_pf <= short_pf
                    else "INSUFFICIENT_EVIDENCE"
                )
            ),
        },
    }
    approved = [
        key
        for key, value in assessments.items()
        if value["recommendation"] == "SUPPORTED_FOR_LIMITED_V2_TEST"
    ][:2]
    for key, value in assessments.items():
        if key not in approved and value["recommendation"] == "SUPPORTED_FOR_LIMITED_V2_TEST":
            value["recommendation"] = "INSUFFICIENT_EVIDENCE"
    return {
        "schema_version": ATTRIBUTION_VERSION,
        "assessments": assessments,
        "approved_for_limited_v2_test": approved,
        "overall_conclusion": "NO_JUSTIFIED_V2_HYPOTHESIS"
        if not approved
        else "LIMITED_HYPOTHESES_IDENTIFIED",
        "authorization_boundary": "RESEARCH_HYPOTHESIS_ONLY_NO_V2_IMPLEMENTATION",
    }


def reconcile_archive(rows: list[dict[str, Any]], archive_report: dict[str, Any]) -> None:
    if len(rows) != EXPECTED_TRADE_COUNT:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: attribution row count")
    if _decimal_sum(row["net_pnl"] for row in rows) != _decimal_sum(
        value["net_pnl_usdt"] for value in archive_report["by_symbol"].values()
    ):
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: net PnL reconciliation")
    for dimension, field in (("by_symbol", "symbol"), ("by_side", "side")):
        for key, expected in archive_report[dimension].items():
            actual = _decimal_sum(row["net_pnl"] for row in rows if row[field] == key)
            if actual != Decimal(expected["net_pnl_usdt"]):
                raise AttributionInputMismatch(f"{INPUT_MISMATCH}: {dimension}/{key}")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _report_markdown(
    *,
    cost: dict[str, Any],
    odds: dict[str, Any],
    hypotheses: dict[str, Any],
    time_exits: list[dict[str, Any]],
    detail_hashes: dict[str, str],
) -> str:
    class_counts = defaultdict(int)
    for row in time_exits:
        class_counts[row["classification"]] += 1
    lines = [
        "# V1 Failure Attribution",
        "",
        "- Frozen conclusion: `STRATEGY_FAILED_BASELINE_VALIDATION`",
        "- Eligibility: `NOT_LIVE_ELIGIBLE` / `DO_NOT_TRADE`",
        f"- Accepted trades reconciled: {EXPECTED_TRADE_COUNT}",
        "- Event engine replayed: `false`",
        "- Analysis boundary: `POST_HOC_DIAGNOSTIC_ONLY`",
        "",
        "## Cost erosion",
        "",
        f"- Fees: {cost['fees']} USDT",
        f"- Slippage: {cost['slippage']} USDT",
        f"- Funding cashflow: {cost['funding_cashflow']} USDT",
        f"- Economic total cost: {cost['economic_total_cost']} USDT",
        f"- Funding income / expense: {cost['funding_income']} / {cost['funding_expense']} USDT",
        f"- Net-winner gross profit / net-loser gross loss: {cost['gross_profit_of_net_winners']} / {cost['gross_loss_of_net_losers']} USDT",
        f"- Profitable before cost but loss after cost: {cost['profitable_before_cost_but_loss_after_cost_count']}",
        f"- MFE insufficient to cover cost: {cost['mfe_insufficient_to_cover_round_trip_cost_count']}",
        f"- Additional average edge for break-even: {cost['additional_average_edge_usdt_per_trade_for_breakeven']} USDT/trade, {cost['additional_average_R_for_breakeven']}R/trade",
        "",
        "## MFE/MAE and TIME_EXIT",
        "",
        f"- Average MFE / MAE: {odds['average_MFE_R']}R / {odds['average_MAE_R']}R",
        f"- Reached 0.5R / 1R / 2R / target: {odds['reached_0_5R_count']} / {odds['reached_1R_count']} / {odds['reached_2R_count']} / {odds['reached_target_count']}",
        f"- TIME_EXIT classifications: {dict(sorted(class_counts.items()))}",
        f"- Trades contributing 80% of gross profit: {odds['trades_contributing_80_percent_of_gross_profit']}",
        f"- Planned net R range: {odds['planned_net_R_minimum']} to {odds['planned_net_R_maximum']}",
        f"- Planned net R conclusion: `{odds['planned_net_R_conclusion']}`",
        "",
        "## Hypothesis assessment",
        "",
    ]
    for key, value in hypotheses["assessments"].items():
        lines.append(f"- {key}: `{value['recommendation']}` — {value['supporting_evidence']}")
    lines.extend(
        (
            "",
            f"Approved for limited V2 test: `{hypotheses['approved_for_limited_v2_test']}`",
            "",
            "No V2 rule or implementation is created by this report.",
            "",
            "## Detailed artifact hashes",
            "",
        )
    )
    lines.extend(f"- `{name}`: `{digest}`" for name, digest in sorted(detail_hashes.items()))
    return "\n".join(lines) + "\n"


def run_attribution(
    *, core_root: Path, archive_root: Path, data_root: Path, output_root: Path
) -> Path:
    if output_root.exists():
        raise FileExistsError(f"output already exists: {output_root}")
    core_verification = _verify_bound_files(core_root)
    manifest = core_verification["manifest"]
    if manifest["experiment_id"] != EXPECTED_EXPERIMENT_ID:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: core experiment identity")
    archive_verification = _verify_archive(archive_root)
    runtime = json.loads((core_root / "runtime_config.json").read_text(encoding="utf-8"))
    approval_path = data_root / "data_approval_manifest_v1.json"
    approval_hash = _sha256_file(approval_path)
    if approval_hash != runtime["data_approval_manifest_hash"]:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: approval manifest hash")
    data_verification = _verify_data_shards(
        data_root, oos_start=runtime["split_start_utc_ms"], oos_end=runtime["split_end_utc_ms"]
    )
    core_rows = _verify_path_equality(core_root)
    trades = core_rows["trades.jsonl"]
    if len(trades) != EXPECTED_TRADE_COUNT:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: trade count {len(trades)}")
    trade_ids = [_trade_id(row) for row in trades]
    if len(set(trade_ids)) != EXPECTED_TRADE_COUNT:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: duplicate trade IDs")
    split = Split("OOS", runtime["split_start_utc_ms"], runtime["split_end_utc_ms"])
    candidates, _, _, _ = _load_candidates(
        data_root,
        split,
        "NATIVE_PRIMARY",
        TRAINING_START_UTC_MS,
        runtime["code_commit"],
        DEPENDENCY_LOCK_HASH,
    )
    candidate_hash = canonical_sha256(candidates)
    if candidate_hash != runtime["candidate_content_hash"]:
        raise AttributionInputMismatch(f"{INPUT_MISMATCH}: candidate content hash")
    rows = _trade_rows(
        core_rows=core_rows,
        candidates=candidates,
        data_root=data_root,
        oos_end=runtime["split_end_utc_ms"],
    )
    archive_report = archive_verification["report"]
    reconcile_archive(rows, archive_report)
    time_exits = time_exit_analysis(rows, data_root)
    costs = cost_attribution(rows)
    subgroups = subgroup_attribution(rows)
    odds = odds_analysis(rows, subgroups)
    hypotheses = hypothesis_assessment(rows, subgroups, time_exits)
    temporary = output_root.with_name(f".{output_root.name}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    _write_csv(temporary / "trade_attribution.csv", rows)
    _write_csv(
        temporary / "mfe_mae_analysis.csv",
        [
            {
                key: value
                for key, value in row.items()
                if key
                in {
                    "trade_id",
                    "candidate_id",
                    "symbol",
                    "side",
                    "entry_time",
                    "exit_time",
                    "availability",
                    "MFE_price",
                    "MAE_price",
                    "MFE_usdt",
                    "MAE_usdt",
                    "MFE_R",
                    "MAE_R",
                    "time_to_MFE_minutes",
                    "time_to_MAE_minutes",
                    "whether_reached_0_5R",
                    "whether_reached_1R",
                    "whether_reached_2R",
                    "whether_reached_target",
                    "whether_price_recovered_after_MAE",
                }
            }
            for row in rows
        ],
    )
    _write_csv(temporary / "time_exit_analysis.csv", time_exits)
    _write_json(temporary / "cost_attribution.json", costs)
    _write_json(temporary / "subgroup_attribution.json", subgroups)
    _write_json(temporary / "odds_analysis.json", odds)
    _write_json(temporary / "hypothesis_assessment.json", hypotheses)
    detail_hashes = {
        path.name: _sha256_file(path) for path in temporary.iterdir() if path.is_file()
    }
    report_text = _report_markdown(
        cost=costs,
        odds=odds,
        hypotheses=hypotheses,
        time_exits=time_exits,
        detail_hashes=detail_hashes,
    )
    (temporary / "v1_failure_attribution_report.md").write_text(
        report_text, encoding="utf-8", newline="\n"
    )
    detailed_hashes = {
        path.name: _sha256_file(path) for path in temporary.iterdir() if path.is_file()
    }
    attribution_manifest = {
        "schema_version": ATTRIBUTION_VERSION,
        "status": "COMPLETE",
        "source_experiment_id": EXPECTED_EXPERIMENT_ID,
        "source_conclusion": "STRATEGY_FAILED_BASELINE_VALIDATION",
        "event_engine_replayed": False,
        "trade_count": len(rows),
        "unique_trade_id_count": len(set(trade_ids)),
        "candidate_count": len(candidates),
        "candidate_content_hash": candidate_hash,
        "core_verification": {
            key: value for key, value in core_verification.items() if key != "manifest"
        },
        "archive_verification": {
            key: value for key, value in archive_verification.items() if key != "report"
        },
        "data_approval_manifest_path": str(approval_path.resolve()),
        "data_approval_manifest_sha256": approval_hash,
        "data_verification": data_verification,
        "artifact_sha256": dict(sorted(detailed_hashes.items())),
        "future_data_policy": POST_HOC,
        "permanent_statuses": [
            "STRATEGY_FAILED_BASELINE_VALIDATION",
            "NOT_LIVE_ELIGIBLE",
            "DO_NOT_TRADE",
        ],
    }
    _write_json(temporary / "attribution_manifest.json", attribution_manifest)
    os.replace(temporary, output_root)
    zip_path = output_root.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_root.iterdir()):
            archive.write(path, arcname=path.name)
    return zip_path
