from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from pa_agent.research_2d.metrics import economic_total_cost

ARCHIVE_SCHEMA_VERSION = "RESEARCH_2D_FAILED_BASELINE_ARCHIVE_V1"
PERMANENT_STATUSES = (
    "STRATEGY_FAILED_BASELINE_VALIDATION",
    "NOT_LIVE_ELIGIBLE",
    "DO_NOT_TRADE",
    "NO_FURTHER_REPLAY_REQUIRED",
)


def _sha256(path: Path) -> str:
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


def verify_source_artifact(source: Path) -> dict[str, object]:
    manifest_path = source / "result_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    for name, expected in sorted(manifest["file_sha256"].items()):
        path = source / name
        actual = _sha256(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({"file": name, "expected": expected, "actual": actual})
    if mismatches:
        raise ValueError(f"source result manifest verification failed: {mismatches}")
    return {
        "source_experiment_id": manifest["experiment_id"],
        "source_task_key": manifest["task_key"],
        "source_result_manifest_sha256": _sha256(manifest_path),
        "verified_file_count": len(manifest["file_sha256"]),
        "mismatches": (),
        "verification_status": "VERIFIED",
    }


def _profit_factor(rows: list[dict[str, object]]) -> Decimal | None:
    profits = sum(
        (Decimal(str(row["net_pnl"])) for row in rows if Decimal(str(row["net_pnl"])) > 0),
        Decimal("0"),
    )
    losses = -sum(
        (Decimal(str(row["net_pnl"])) for row in rows if Decimal(str(row["net_pnl"])) < 0),
        Decimal("0"),
    )
    return profits / losses if losses else None


def _breakdown(rows: list[dict[str, object]], key: str) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    result = {}
    for name, group in sorted(grouped.items()):
        net_pnl = sum((Decimal(str(row["net_pnl"])) for row in group), Decimal("0"))
        profit_factor = _profit_factor(group)
        result[name] = {
            "trade_count": len(group),
            "net_pnl_usdt": str(net_pnl),
            "display_net_pnl_usdt": f"{net_pnl:+.4f}",
            "profit_factor": str(profit_factor) if profit_factor is not None else None,
            "display_profit_factor": (
                f"{profit_factor:.4f}" if profit_factor is not None else None
            ),
        }
    return result


def build_archive_report(
    *,
    source_experiment_id: str,
    metric: dict[str, object],
    trades: list[dict[str, object]],
    engine_peak_observed_drawdown: Decimal,
) -> dict[str, object]:
    fees = Decimal(str(metric["fees"]))
    slippage = Decimal(str(metric["slippage"]))
    funding_cashflow = Decimal(str(metric.get("funding_cashflow", metric.get("funding"))))
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "source_experiment_id": source_experiment_id,
        "permanent_statuses": PERMANENT_STATUSES,
        "final_conclusion": "STRATEGY_FAILED_BASELINE_VALIDATION",
        "live_eligibility": "NOT_LIVE_ELIGIBLE",
        "trade_directive": "DO_NOT_TRADE",
        "replay_directive": "NO_FURTHER_REPLAY_REQUIRED",
        "economic_metrics": {
            "net_return": str(metric["net_return"]),
            "annualized_return": str(metric["annualized_return"]),
            "profit_factor": str(metric["profit_factor"]),
            "sharpe": str(metric["sharpe"]),
            "win_rate": str(metric["win_rate"]),
            "trade_count": int(metric["trade_count"]),
        },
        "drawdown": {
            "daily_close_max_drawdown": str(
                Decimal(
                    str(metric.get("daily_close_max_drawdown", metric.get("maximum_drawdown")))
                ).quantize(Decimal("0.0000000000000001"), rounding=ROUND_HALF_EVEN)
            ),
            "engine_peak_observed_drawdown": str(engine_peak_observed_drawdown),
            "engine_peak_observed_drawdown_provenance": "INDEPENDENT_ACCEPTANCE_AUDIT",
        },
        "costs_usdt": {
            "fees": str(fees),
            "slippage": str(slippage),
            "funding_cashflow": str(funding_cashflow),
            "economic_total_cost": str(
                economic_total_cost(
                    fees=fees,
                    slippage=slippage,
                    funding_cashflow=funding_cashflow,
                )
            ),
            "formula": "fees + slippage - funding_cashflow",
        },
        "by_symbol": _breakdown(trades, "symbol"),
        "by_side": _breakdown(trades, "side"),
        "by_exit_reason": _breakdown(trades, "exit_reason"),
        "source_integrity": {
            "minute_engine_replayed": False,
            "trades_modified": False,
            "ledger_modified": False,
            "net_return_modified": False,
        },
    }


def _markdown(report: dict[str, object]) -> str:
    economic = report["economic_metrics"]
    drawdown = report["drawdown"]
    costs = report["costs_usdt"]
    lines = [
        "# 2D Core OOS Failed-Baseline Archive",
        "",
        f"- Final conclusion: `{report['final_conclusion']}`",
        "- Permanent status: `NOT_LIVE_ELIGIBLE`, `DO_NOT_TRADE`, `NO_FURTHER_REPLAY_REQUIRED`",
        f"- Source experiment: `{report['source_experiment_id']}`",
        "- Minute engine replayed: `false`",
        "",
        "## Core metrics",
        "",
        f"- Net return: {economic['net_return']}",
        f"- Annualized return: {economic['annualized_return']}",
        f"- Profit Factor: {economic['profit_factor']}",
        f"- Sharpe: {economic['sharpe']}",
        f"- Win rate: {economic['win_rate']}",
        f"- Trades: {economic['trade_count']}",
        f"- Daily-close max drawdown: {drawdown['daily_close_max_drawdown']}",
        f"- Engine peak-observed drawdown: {drawdown['engine_peak_observed_drawdown']}",
        "",
        "## Costs (USDT)",
        "",
        f"- Fees: {costs['fees']}",
        f"- Slippage: {costs['slippage']}",
        f"- Funding cashflow: {costs['funding_cashflow']}",
        f"- Economic total cost: {costs['economic_total_cost']}",
        "- Formula: `fees + slippage - funding_cashflow`",
    ]
    for title, key in (
        ("Symbol breakdown", "by_symbol"),
        ("Side breakdown", "by_side"),
        ("Exit-reason breakdown", "by_exit_reason"),
    ):
        lines.extend(("", f"## {title}", ""))
        for name, value in report[key].items():
            line = f"- {name}: {value['display_net_pnl_usdt']} USDT"
            if value["profit_factor"] is not None:
                line += f", PF {value['display_profit_factor']}"
            lines.append(line)
    return "\n".join(lines) + "\n"


def archive_failed_baseline(
    source: Path,
    output_root: Path,
    *,
    engine_peak_observed_drawdown: Decimal,
) -> Path:
    verification = verify_source_artifact(source)
    metrics = json.loads((source / "metrics.json").read_text(encoding="utf-8"))
    baseline = next(row for row in metrics if row["path_kind"] == "BASELINE")
    conservative = next(row for row in metrics if row["path_kind"] == "CONSERVATIVE")
    if {key: value for key, value in baseline.items() if key != "path_kind"} != {
        key: value for key, value in conservative.items() if key != "path_kind"
    }:
        raise ValueError("BASELINE and CONSERVATIVE metrics differ")
    path_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    with (source / "trades.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            path_rows[item["path_kind"]].append(item["value"])
    if path_rows["BASELINE"] != path_rows["CONSERVATIVE"]:
        raise ValueError("BASELINE and CONSERVATIVE trades differ")
    report = build_archive_report(
        source_experiment_id=str(verification["source_experiment_id"]),
        metric=baseline,
        trades=path_rows["BASELINE"],
        engine_peak_observed_drawdown=engine_peak_observed_drawdown,
    )
    archive_id = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    target = output_root / archive_id
    temporary = output_root / f".{archive_id}.tmp"
    if target.exists():
        return target
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    _write_json(
        temporary / "PERMANENT_STATUS.json",
        {
            "source_experiment_id": verification["source_experiment_id"],
            "statuses": PERMANENT_STATUSES,
        },
    )
    _write_json(temporary / "archival_report.json", report)
    (temporary / "archival_report.md").write_text(_markdown(report), encoding="utf-8")
    _write_json(temporary / "source_verification.json", verification)
    files = {path.name: _sha256(path) for path in temporary.iterdir() if path.is_file()}
    _write_json(
        temporary / "archive_manifest.json",
        {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": archive_id,
            "source_experiment_id": verification["source_experiment_id"],
            "file_sha256": dict(sorted(files.items())),
        },
    )
    os.replace(temporary, target)
    return target
