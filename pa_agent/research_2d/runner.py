from __future__ import annotations

import csv
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pa_agent.research_2d.approval import sha256_file, verify_data_approval_manifest
from pa_agent.research_2d.benchmarks import benchmark_metrics
from pa_agent.research_2d.data import (
    SUPPORTED_SYMBOLS,
    build_actionable_candidate_stream,
    iter_canonical_records,
    iter_joint_minute_slices,
    load_strategy_bars,
)
from pa_agent.research_2d.evidence import (
    CONTRACT_RULE_VERSION,
    MAINTENANCE_VERSION,
    EvidenceRequest,
    build_evidence_catalog,
)
from pa_agent.research_2d.identity import (
    build_experiment_identity_payload,
    computational_experiment_id,
)
from pa_agent.research_2d.metrics import oos_confidence_intervals, summarize_path
from pa_agent.research_2d.streaming import STREAMING_ADAPTER_VERSION, run_streaming_paths
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig
from pa_agent.research_backtest.simulation.context import make_production_run_context
from pa_agent.research_backtest.simulation.domain import make_simulation_config
from pa_agent.research_backtest.simulation.inputs import SimulationInputs
from pa_agent.research_backtest.simulation.versions import MINUTE_ENGINE_VERSION
from pa_agent.research_backtest.versions import (
    CANONICAL_2B_VERSION,
    FEE_MODEL_VERSION,
    FUNDING_BUFFER_MODEL_VERSION,
    INDICATOR_CONFIG_VERSION,
    SLIPPAGE_MODEL_VERSION,
    STRATEGY_VERSION,
)

AUTHORITIES = ("NATIVE_PRIMARY", "AGGREGATED_AUDIT_SENSITIVITY")
INITIAL_CAPITAL = Decimal("10000")
BASE_SLIPPAGE = {"BTCUSDT": Decimal("0.0001"), "ETHUSDT": Decimal("0.0002")}


@dataclass(frozen=True, slots=True)
class Split:
    name: str
    start_utc_ms: int
    end_utc_ms: int

    @property
    def end_exit_open_utc_ms(self) -> int:
        return self.end_utc_ms + 1


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    cost_multiplier: Decimal
    funding_multiplier: Decimal
    fee_scale: Decimal = Decimal("1")
    slippage_scale: Decimal = Decimal("1")


def _utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _splits(value: dict[str, Any]) -> tuple[Split, ...]:
    return tuple(
        Split(
            name,
            _utc_ms(value[f"{name.lower()}_start_utc"]),
            _utc_ms(value[f"{name.lower()}_end_utc"]),
        )
        for name in ("TRAINING", "VALIDATION", "OOS")
    )


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def canonical_report_value(value: object) -> object:
    """Quantize binary indicator/statistic floats at the frozen report boundary."""
    if isinstance(value, float):
        return float64_to_decimal_15sig(value)
    if isinstance(value, dict):
        return {key: canonical_report_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(canonical_report_value(item) for item in value)
    return value


def _load_candidates(
    root: Path,
    split: Split,
    authority: str,
    training_start: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> tuple[
    tuple[object, ...], tuple[object, ...], dict[str, dict[str, int]], dict[str, tuple[object, ...]]
]:
    candidates = []
    trends = []
    counts = {}
    daily_by_symbol = {}
    pre_roll_start = _utc_ms("2020-01-01T00:00:00Z")
    authority_key = "NATIVE_PRIMARY" if authority == "NATIVE_PRIMARY" else "AGGREGATED_SENSITIVITY"
    for symbol in SUPPORTED_SYMBOLS:
        bars = load_strategy_bars(
            root,
            symbol=symbol,
            authority=authority_key,
            start_utc_ms=pre_roll_start,
            end_utc_ms=split.end_utc_ms,
        )
        stream = build_actionable_candidate_stream(
            symbol=symbol,
            daily_bars=bars.daily,
            four_hour_bars=bars.four_hour,
            training_start_utc_ms=training_start,
            decision_start_utc_ms=split.start_utc_ms,
            decision_end_utc_ms=split.end_utc_ms,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
        candidates.extend(stream.candidates)
        trends.extend(stream.trend_evidence)
        counts[symbol] = stream.market_view_counts
        daily_by_symbol[symbol] = bars.daily
    return (
        tuple(sorted(candidates, key=lambda item: (item.decision_time_utc_ms, item.symbol))),
        tuple(sorted(trends, key=lambda item: (item.decision_time_utc_ms, item.symbol))),
        counts,
        daily_by_symbol,
    )


def _market_evidence(
    root: Path,
    split: Split,
    candidates: tuple[object, ...],
) -> tuple[
    tuple[tuple[str, int, Decimal], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, tuple[int, ...]], ...],
    tuple[tuple[str, int, Decimal], ...],
]:
    entry_targets = tuple(
        sorted((item.symbol, item.decision_time_utc_ms + 1 + 60_000) for item in candidates)
    )
    required = set(entry_targets)
    for symbol, entry_time in entry_targets:
        time_exit = entry_time + 48 * 60 * 60 * 1000 + 60_000
        if time_exit <= split.end_exit_open_utc_ms:
            required.add((symbol, time_exit))
    first_boundary = (split.start_utc_ms // 14_400_000 + 1) * 14_400_000
    for time in range(first_boundary, split.end_exit_open_utc_ms + 1, 14_400_000):
        for symbol in SUPPORTED_SYMBOLS:
            required.add((symbol, time))
    for symbol in SUPPORTED_SYMBOLS:
        required.add((symbol, split.end_exit_open_utc_ms))
    prices = []
    for symbol in SUPPORTED_SYMBOLS:
        wanted = {time for item_symbol, time in required if item_symbol == symbol}
        for row in iter_canonical_records(root, symbol, "trade_1m", min(wanted), max(wanted)):
            time = int(row["open_time_utc_ms"])
            if time in wanted:
                prices.append((symbol, time, Decimal(str(row["open"]))))
    funding_times = []
    caps = []
    pre_roll_start = _utc_ms("2020-01-01T00:00:00Z")
    for symbol in SUPPORTED_SYMBOLS:
        records = tuple(
            iter_canonical_records(root, symbol, "funding", pre_roll_start, split.end_utc_ms)
        )
        times_rates = tuple(
            (
                int(row["funding_time_utc_ms"]) // 60_000 * 60_000,
                abs(Decimal(str(row["funding_rate"]))),
            )
            for row in records
        )
        funding_times.append(
            (
                symbol,
                tuple(
                    time
                    for time, _ in times_rates
                    if split.start_utc_ms <= time <= split.end_utc_ms
                ),
            )
        )
        maximum = Decimal("0")
        cursor = 0
        symbol_targets = sorted(
            time for item_symbol, time in entry_targets if item_symbol == symbol
        )
        for target in symbol_targets:
            while cursor < len(times_rates) and times_rates[cursor][0] <= target:
                maximum = max(maximum, times_rates[cursor][1])
                cursor += 1
            caps.append((symbol, target, maximum))
    return tuple(prices), tuple(sorted(required)), tuple(funding_times), tuple(caps)


def _gap_intervals(root: Path, split: Split) -> tuple[tuple[str, int, int], ...]:
    report = json.loads((root / "mark_gap_materiality.json").read_text(encoding="utf-8"))
    return tuple(
        (item["symbol"], _utc_ms(item["start_utc"]), _utc_ms(item["end_utc"]) // 60_000 * 60_000)
        for item in report["gaps"]
        if item["split"] == split.name
    )


def _run_scenario(
    *,
    root: Path,
    split: Split,
    authority: str,
    scenario: Scenario,
    candidates: tuple[object, ...],
    trends: tuple[object, ...],
    evidence_data: tuple[object, ...],
    experiment_id: str,
    approval_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> tuple[tuple[object, ...], list[dict[str, object]]]:
    prices, required, funding_times, caps = evidence_data
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    fee_rate = Decimal("0.0005") * scenario.fee_scale
    slippage = {
        symbol: BASE_SLIPPAGE[symbol] * scenario.slippage_scale for symbol in SUPPORTED_SYMBOLS
    }
    request = EvidenceRequest(
        split_start_utc_ms=split.start_utc_ms,
        split_end_exit_open_utc_ms=split.end_exit_open_utc_ms,
        target_prices=prices,
        required_targets=required,
        entry_targets=tuple(
            sorted((item.symbol, item.decision_time_utc_ms + 1 + 60_000) for item in candidates)
        ),
        funding_times=funding_times,
        funding_rate_caps=caps,
        fee_rate=fee_rate,
        slippage_rates=tuple(sorted(slippage.items())),
        cost_stress_multiplier=scenario.cost_multiplier,
        funding_stress_multiplier=scenario.funding_multiplier,
        source_manifest_hash=approval_hash,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    catalog = build_evidence_catalog(request)
    config = make_simulation_config(
        symbols=SUPPORTED_SYMBOLS,
        simulation_start_utc_ms=split.start_utc_ms,
        simulation_end_exit_open_utc_ms=split.end_exit_open_utc_ms,
        initial_wallet_balance=INITIAL_CAPITAL,
        cost_model_version=f"{FEE_MODEL_VERSION}:{SLIPPAGE_MODEL_VERSION}:{scenario.name}",
        funding_model_version=f"{FUNDING_BUFFER_MODEL_VERSION}:{scenario.name}",
        two_a_version=INDICATOR_CONFIG_VERSION,
        two_b_planner_version=CANONICAL_2B_VERSION,
        two_b_planner_config_hash=execution.config_content_hash,
        two_c_engine_version=MINUTE_ENGINE_VERSION,
        code_commit=code_commit,
        dependency_lock_hash=dependency_lock_hash,
    )
    identity_inputs = SimulationInputs(
        (), candidates, (("approved_historical_bundle", request.source_manifest_hash),)
    )
    context = make_production_run_context(
        inputs=identity_inputs,
        config=config,
        evidence_catalog=catalog,
        execution_time_config=execution,
        computational_experiment_id=experiment_id,
    )
    runs = run_streaming_paths(
        context,
        iter_joint_minute_slices(
            root,
            start_utc_ms=split.start_utc_ms,
            end_utc_ms=split.end_exit_open_utc_ms,
            funding_multiplier=scenario.funding_multiplier,
            trend_evidence=trends,
        ),
        gap_intervals=_gap_intervals(root, split),
    )
    metrics = [
        summarize_path(
            run,
            initial_capital=INITIAL_CAPITAL,
            split_start_utc_ms=split.start_utc_ms,
            split_end_utc_ms=split.end_utc_ms,
            slippage_rates={
                symbol: slippage[symbol] * scenario.cost_multiplier for symbol in SUPPORTED_SYMBOLS
            },
        )
        for run in runs
    ]
    return runs, metrics


def _conclusion(oos_metrics: list[dict[str, object]], oos_runs: tuple[object, ...]) -> str:
    if any(item["path_state"] != "VALID" for item in oos_metrics):
        return "DATA_EXECUTION_INVALID"
    if any(int(item["trade_count"]) < 60 for item in oos_metrics):
        return "INSUFFICIENT_STATISTICAL_EVIDENCE"
    if any(
        Decimal(str(item["net_return"])) <= 0
        or Decimal(str(item["maximum_drawdown"])) >= Decimal("0.10")
        for item in oos_metrics
    ):
        return "STRATEGY_FAILED_BASELINE_VALIDATION"
    cis = [oos_confidence_intervals(run, INITIAL_CAPITAL) for run in oos_runs]
    if any(
        value[name]["status"] != "DEFINED" or value[name]["lower_95"] <= threshold
        for value in cis
        for name, threshold in (("daily_net_return", 0), ("profit_factor", 1))
    ):
        return "INSUFFICIENT_STATISTICAL_EVIDENCE"
    return "CONTINUE_TO_ROBUST_VALIDATION"


def run_baseline_evaluation(
    *,
    root: Path,
    output_root: Path,
    code_commit: str,
) -> Path:
    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    split_manifest_path = root / "experiment_split_candidate_v3.json"
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    splits = _splits(split_manifest)
    execution = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    identity_payload = build_experiment_identity_payload(
        {
            "approved_data_bundle_hash": approval.manifest["hybrid_historical_data_bundle_hash"],
            "data_approval_manifest_hash": approval.manifest_hash,
            "split_manifest_hash": sha256_file(split_manifest_path),
            "authority_policy_version": approval.manifest["authority_policy_version"],
            "strategy_version": STRATEGY_VERSION,
            "two_a_version": INDICATOR_CONFIG_VERSION,
            "two_b_version": CANONICAL_2B_VERSION,
            "planner_config_hash": execution.config_content_hash,
            "two_c_version": MINUTE_ENGINE_VERSION,
            "fee_model_version": FEE_MODEL_VERSION,
            "slippage_model_version": SLIPPAGE_MODEL_VERSION,
            "funding_model_version": FUNDING_BUFFER_MODEL_VERSION,
            "contract_approximation_version": CONTRACT_RULE_VERSION,
            "maintenance_approximation_version": MAINTENANCE_VERSION,
            "path_policy_version": "BASELINE_CONSERVATIVE_PATHS_V1",
            "code_commit": code_commit,
            "dependency_lock_hash": approval.manifest["dependency_lock_hash"],
        }
    )
    experiment_id = computational_experiment_id(identity_payload)
    final = output_root / experiment_id
    if final.exists():
        raise FileExistsError(f"result already exists: {final}")
    temporary = output_root / f".{experiment_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    experiment_manifest = {
        "schema_version": "RESEARCH_2D_EXPERIMENT_MANIFEST_V1",
        "computational_experiment_id": experiment_id,
        "identity": identity_payload,
        "split_candidate": split_manifest,
        "authorities": AUTHORITIES,
        "scenarios": ["BASE_1X", "COMBINED_2X", "FEE_SLIPPAGE_3X", "FUNDING_2X"],
        "streaming_adapter_version": STREAMING_ADAPTER_VERSION,
        "permanent_watermarks": approval.manifest["permanent_watermarks"],
    }
    all_metrics: dict[str, Any] = {}
    all_runs: dict[tuple[str, str, str], tuple[object, ...]] = {}
    candidates_meta = {}
    benchmarks = {}
    training_start = splits[0].start_utc_ms
    base = Scenario("BASE_1X", Decimal("1"), Decimal("1"))
    for split in splits:
        for authority in AUTHORITIES:
            candidates, trends, counts, daily = _load_candidates(
                root,
                split,
                authority,
                training_start,
                code_commit,
                approval.manifest["dependency_lock_hash"],
            )
            evidence_data = _market_evidence(root, split, candidates)
            runs, metrics = _run_scenario(
                root=root,
                split=split,
                authority=authority,
                scenario=base,
                candidates=candidates,
                trends=trends,
                evidence_data=evidence_data,
                experiment_id=experiment_id,
                approval_hash=approval.manifest_hash,
                code_commit=code_commit,
                dependency_lock_hash=approval.manifest["dependency_lock_hash"],
            )
            key = f"{split.name}:{authority}:BASE_1X"
            all_metrics[key] = metrics
            all_runs[(split.name, authority, "BASE_1X")] = runs
            candidates_meta[f"{split.name}:{authority}"] = {
                "actionable_count": len(candidates),
                "market_view_counts": counts,
                "candidate_content_hash": canonical_sha256(candidates),
            }
            benchmarks[f"{split.name}:{authority}"] = benchmark_metrics(
                daily,
                split_start_utc_ms=split.start_utc_ms,
                split_end_utc_ms=split.end_utc_ms,
            )
    oos = splits[-1]
    native_candidates, native_trends, _, _ = _load_candidates(
        root,
        oos,
        "NATIVE_PRIMARY",
        training_start,
        code_commit,
        approval.manifest["dependency_lock_hash"],
    )
    native_evidence = _market_evidence(root, oos, native_candidates)
    stresses = (
        Scenario("COMBINED_2X", Decimal("2"), Decimal("2")),
        Scenario("FEE_SLIPPAGE_3X", Decimal("1"), Decimal("1"), Decimal("3"), Decimal("3")),
        Scenario("FUNDING_2X", Decimal("1"), Decimal("2")),
    )
    cost_stress = {}
    for scenario in stresses:
        runs, metrics = _run_scenario(
            root=root,
            split=oos,
            authority="NATIVE_PRIMARY",
            scenario=scenario,
            candidates=native_candidates,
            trends=native_trends,
            evidence_data=native_evidence,
            experiment_id=experiment_id,
            approval_hash=approval.manifest_hash,
            code_commit=code_commit,
            dependency_lock_hash=approval.manifest["dependency_lock_hash"],
        )
        all_runs[("OOS", "NATIVE_PRIMARY", scenario.name)] = runs
        cost_stress[scenario.name] = metrics
    oos_runs = all_runs[("OOS", "NATIVE_PRIMARY", "BASE_1X")]
    oos_metrics = all_metrics["OOS:NATIVE_PRIMARY:BASE_1X"]
    confidence = {
        run.path_kind.value: oos_confidence_intervals(run, INITIAL_CAPITAL) for run in oos_runs
    }
    conclusion = _conclusion(oos_metrics, oos_runs)
    native_metrics = {key: value for key, value in all_metrics.items() if ":NATIVE_PRIMARY:" in key}
    aggregated_metrics = {
        key: value for key, value in all_metrics.items() if ":AGGREGATED_AUDIT_SENSITIVITY:" in key
    }
    gap_impact = {
        ":".join(key): {run.path_kind.value: run.gap_context for run in runs}
        for key, runs in all_runs.items()
        if key[2] == "BASE_1X"
    }
    rejection_summary = {
        key: {item["path_kind"]: item["execution_rejections"] for item in values}
        for key, values in all_metrics.items()
    }
    summary = {
        "computational_experiment_id": experiment_id,
        "conclusion": conclusion,
        "oos_native_primary": oos_metrics,
        "confidence_intervals": confidence,
        "candidate_summary": candidates_meta,
        "watermarks": approval.manifest["permanent_watermarks"],
    }
    files = {
        "data_approval_manifest.json": approval.manifest,
        "experiment_manifest.json": experiment_manifest,
        "metrics_summary.json": summary,
        "native_primary_metrics.json": native_metrics,
        "aggregated_sensitivity_metrics.json": aggregated_metrics,
        "mark_gap_impact.json": gap_impact,
        "rejection_summary.json": rejection_summary,
        "benchmark_comparison.json": benchmarks,
        "cost_stress.json": cost_stress,
    }
    for name, value in files.items():
        _atomic_text(temporary / name, canonical_dumps(canonical_report_value(value)) + "\n")
    with (temporary / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("split", "authority", "scenario", "path", "trade_json"))
        for key, runs in sorted(all_runs.items()):
            for run in runs:
                for trade in run.trades:
                    writer.writerow((*key, run.path_kind.value, canonical_dumps(trade)))
    with (temporary / "equity_daily.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("split", "authority", "scenario", "path", "equity_json"))
        for key, runs in sorted(all_runs.items()):
            for run in runs:
                for point in run.daily_equity_points:
                    writer.writerow((*key, run.path_kind.value, canonical_dumps(point)))
    report = (
        "# BTC/ETH 2D Baseline Evaluation\n\n"
        f"- Experiment: `{experiment_id}`\n"
        f"- Conclusion: `{conclusion}`\n"
        "- Authority: native Binance 4H/1D; aggregated bars are audit sensitivity only.\n"
        "- Execution: frozen 2B planning and 2C minute engine, isolated 1x.\n"
        "- Watermarks: APPROXIMATED execution infrastructure; NOT_EXCHANGE_EXACT; NOT_LIVE_ELIGIBLE.\n"
        "- This report does not authorize paper, live, account, or order access.\n"
    )
    _atomic_text(temporary / "baseline_report.md", report)
    hashes = {
        path.name: sha256_file(path)
        for path in sorted(temporary.iterdir())
        if path.name != "result_manifest.json"
    }
    result_manifest = {
        "schema_version": "RESEARCH_2D_RESULT_MANIFEST_V1",
        "computational_experiment_id": experiment_id,
        "conclusion": conclusion,
        "file_sha256": hashes,
    }
    _atomic_text(temporary / "result_manifest.json", canonical_dumps(result_manifest) + "\n")
    os.replace(temporary, final)
    return final
