from __future__ import annotations

import csv
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
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
from pa_agent.research_2d.parallel import (
    EvaluationTask,
    TaskExecutionBatch,
    exclusive_output_lock,
    formal_task_keys,
    run_tasks,
)
from pa_agent.research_2d.streaming import STREAMING_ADAPTER_VERSION, run_streaming_paths
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.rejections import ExecutionRejection
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


class TaskDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    DIAGNOSTIC_DATA_GAP = "DIAGNOSTIC_DATA_GAP"


class FormalEvaluationGateError(RuntimeError):
    def __init__(self, task_key: str, reason: str) -> None:
        self.task_key = task_key
        self.reason = reason
        self.conclusion = "DATA_EXECUTION_INVALID"
        super().__init__(f"DATA_EXECUTION_INVALID:{task_key}:{reason}")


AUTHORITATIVE_REQUIRED = frozenset(
    {
        "OOS:NATIVE_PRIMARY:BASE_1X",
        "OOS:NATIVE_PRIMARY:COMBINED_2X",
        "OOS:NATIVE_PRIMARY:FEE_SLIPPAGE_3X",
        "OOS:NATIVE_PRIMARY:FUNDING_2X",
    }
)
SENSITIVITY_REQUIRED = frozenset({"OOS:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X"})
DIAGNOSTIC_NON_GATING = frozenset(
    {
        "VALIDATION:NATIVE_PRIMARY:BASE_1X",
        "VALIDATION:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
        "TRAINING:NATIVE_PRIMARY:BASE_1X",
        "TRAINING:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X",
    }
)


def _task_class(task_key: str) -> str:
    if task_key in AUTHORITATIVE_REQUIRED:
        return "AUTHORITATIVE_REQUIRED"
    if task_key in SENSITIVITY_REQUIRED:
        return "SENSITIVITY_REQUIRED"
    if task_key in DIAGNOSTIC_NON_GATING:
        return "DIAGNOSTIC_NON_GATING"
    raise FormalEvaluationGateError(task_key, "UNKNOWN_TASK_CLASS")


def assess_formal_task_result(result: object) -> SimpleNamespace:
    task_key = str(result.key)
    task_class = _task_class(task_key)
    runs = tuple(result.runs)
    metrics = tuple(result.metrics)
    if len(runs) != len(metrics) or not runs:
        raise FormalEvaluationGateError(task_key, "PATH_RESULT_CARDINALITY_INVALID")
    if {run.path_kind.value for run in runs} != {"BASELINE", "CONSERVATIVE"}:
        raise FormalEvaluationGateError(task_key, "PATH_RESULT_SET_INVALID")
    invalid_reasons = tuple(
        run.path_result.invalid_reason
        for run in runs
        if run.path_result.path_state.value == "INVALID"
    )
    has_data_invalid = any(
        isinstance(item, ExecutionRejection) and item.reason.value == "DATA_INVALID"
        for run in runs
        for item in run.planning_outputs
    )
    incomplete = any(
        run.path_result.final_processed_time_utc_ms != int(metric["split_end_utc_ms"]) + 1
        for run, metric in zip(runs, metrics, strict=True)
    )
    non_valid = any(run.path_result.path_state.value != "VALID" for run in runs)
    mark_gap_only = bool(invalid_reasons) and all(
        isinstance(reason, str) and reason.startswith("MARK_GAP_AFFECTS_POSITION")
        for reason in invalid_reasons
    )
    if (
        task_class == "DIAGNOSTIC_NON_GATING"
        and mark_gap_only
        and not has_data_invalid
        and all(run.path_result.path_state.value == "INVALID" for run in runs)
    ):
        return SimpleNamespace(
            task_key=task_key,
            task_class=task_class,
            status=TaskDisposition.DIAGNOSTIC_DATA_GAP,
        )
    if has_data_invalid or non_valid or incomplete:
        reason = (
            "DATA_INVALID"
            if has_data_invalid
            else invalid_reasons[0]
            if invalid_reasons
            else "SPLIT_NOT_COMPLETED"
        )
        raise FormalEvaluationGateError(task_key, str(reason))
    return SimpleNamespace(
        task_key=task_key,
        task_class=task_class,
        status=TaskDisposition.COMPLETED,
    )


def performance_results(results: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(
        result
        for result in results
        if assess_formal_task_result(result).status is TaskDisposition.COMPLETED
    )


def run_prioritized_task_phases(
    tasks: tuple[object, ...],
    *,
    max_workers: int,
    hard_timeout_seconds: float,
    no_progress_timeout_seconds: float | None,
    batch_runner=run_tasks,
) -> TaskExecutionBatch:
    by_phase = (
        tuple(task for task in tasks if str(task.key).startswith("OOS:")),
        tuple(task for task in tasks if str(task.key).startswith("VALIDATION:")),
        tuple(task for task in tasks if str(task.key).startswith("TRAINING:")),
    )
    results = []
    batches = []
    for phase in by_phase:
        if not phase:
            continue
        batch = batch_runner(
            phase,
            max_workers=max_workers,
            hard_timeout_seconds=hard_timeout_seconds,
            no_progress_timeout_seconds=no_progress_timeout_seconds,
            result_validator=assess_formal_task_result,
        )
        batches.append(batch)
        results.extend(batch.results)
    result_by_key = {str(result.key): result for result in results}
    return TaskExecutionBatch(
        results=tuple(result_by_key[str(task.key)] for task in tasks),
        multiprocessing_start_method=batches[0].multiprocessing_start_method,
        parent_peak_rss_bytes=max(batch.parent_peak_rss_bytes for batch in batches),
        aggregate_worker_peak_rss_bytes=max(
            batch.aggregate_worker_peak_rss_bytes for batch in batches
        ),
        heartbeats=tuple(item for batch in batches for item in batch.heartbeats),
    )


def load_known_training_gap_evidence(
    mark_gap_path: Path, *, approved_data_bundle_hash: str
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    mark_gap_path = mark_gap_path.resolve()
    directory = mark_gap_path.parent
    experiment_path = directory / "experiment_manifest.json"
    result_path = directory / "result_manifest.json"
    native_path = directory / "native_primary_metrics.json"
    aggregated_path = directory / "aggregated_sensitivity_metrics.json"
    for path in (mark_gap_path, experiment_path, result_path, native_path, aggregated_path):
        if not path.is_file():
            raise ValueError(f"known diagnostic evidence missing: {path.name}")
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    result_manifest = json.loads(result_path.read_text(encoding="utf-8"))
    identity = experiment.get("identity", {})
    expected_identity = {
        "approved_data_bundle_hash": approved_data_bundle_hash,
        "strategy_version": STRATEGY_VERSION,
        "two_c_version": MINUTE_ENGINE_VERSION,
    }
    for name, expected in expected_identity.items():
        if identity.get(name) != expected:
            raise ValueError(f"known diagnostic evidence identity mismatch: {name}")
    declared_hashes = result_manifest.get("file_sha256", {})
    for path in (mark_gap_path, native_path, aggregated_path):
        if declared_hashes.get(path.name) != sha256_file(path):
            raise ValueError(f"known diagnostic evidence hash mismatch: {path.name}")
    gap_impact = json.loads(mark_gap_path.read_text(encoding="utf-8"))
    metrics_by_file = {
        "NATIVE_PRIMARY": json.loads(native_path.read_text(encoding="utf-8")),
        "AGGREGATED_AUDIT_SENSITIVITY": json.loads(aggregated_path.read_text(encoding="utf-8")),
    }
    diagnostics: dict[str, dict[str, object]] = {}
    for authority, metrics_file in metrics_by_file.items():
        key = f"TRAINING:{authority}:BASE_1X"
        path_metrics = metrics_file.get(key)
        path_gaps = gap_impact.get(key)
        if not isinstance(path_metrics, list) or not isinstance(path_gaps, dict):
            raise ValueError(f"known diagnostic evidence incomplete: {key}")
        if {item.get("path_kind") for item in path_metrics} != {
            "BASELINE",
            "CONSERVATIVE",
        }:
            raise ValueError(f"known diagnostic path set mismatch: {key}")
        if any(
            item.get("path_state") != "INVALID"
            or not str(item.get("invalid_reason", "")).startswith("MARK_GAP_AFFECTS_POSITION")
            for item in path_metrics
        ):
            raise ValueError(f"known diagnostic reason mismatch: {key}")
        material_gaps = [
            gap
            for gaps in path_gaps.values()
            for gap in gaps
            if gap.get("open_position_crosses") and int(gap.get("invalid_episode_count", 0)) > 0
        ]
        if not material_gaps:
            raise ValueError(f"known diagnostic material gap missing: {key}")
        first_start = min(int(item["start_utc_ms"]) for item in material_gaps)
        first_gaps = [item for item in material_gaps if int(item["start_utc_ms"]) == first_start]
        processed_counts = {int(item["processed_minute_count"]) for item in path_metrics}
        if len(processed_counts) != 1:
            raise ValueError(f"known diagnostic processed count mismatch: {key}")
        affected_symbols = sorted({str(item["symbol"]) for item in first_gaps})
        diagnostics[key] = {
            "status": TaskDisposition.DIAGNOSTIC_DATA_GAP,
            "first_invalid_time_utc_ms": first_start,
            "gap_start_utc_ms": first_start,
            "gap_end_utc_ms": max(int(item["end_utc_ms"]) for item in first_gaps),
            "affected_symbols": affected_symbols,
            "affected_positions": [
                {"symbol": symbol, "open_position_crosses": True} for symbol in affected_symbols
            ],
            "processed_minute_count": processed_counts.pop(),
            "path_kinds": ["BASELINE", "CONSERVATIVE"],
        }
    binding = {
        "schema_version": "KNOWN_DIAGNOSTIC_GAP_EVIDENCE_V1",
        "source_experiment_id": experiment["computational_experiment_id"],
        "approved_data_bundle_hash": approved_data_bundle_hash,
        "mark_gap_impact_sha256": sha256_file(mark_gap_path),
        "source_result_manifest_sha256": sha256_file(result_path),
        "strategy_version": STRATEGY_VERSION,
        "two_c_version": MINUTE_ENGINE_VERSION,
    }
    return diagnostics, binding


def diagnostic_gap_record(result: object) -> dict[str, object]:
    disposition = assess_formal_task_result(result)
    if disposition.status is not TaskDisposition.DIAGNOSTIC_DATA_GAP:
        raise ValueError("result is not a diagnostic data gap")
    material_gaps = [
        gap
        for run in result.runs
        for gap in run.gap_context
        if gap.get("open_position_crosses") and int(gap.get("invalid_episode_count", 0)) > 0
    ]
    first_invalid = min(int(run.path_result.final_processed_time_utc_ms) for run in result.runs)
    first_gaps = [gap for gap in material_gaps if int(gap["start_utc_ms"]) == first_invalid]
    affected_symbols = sorted({str(item["symbol"]) for item in first_gaps})
    return {
        "status": TaskDisposition.DIAGNOSTIC_DATA_GAP,
        "first_invalid_time_utc_ms": first_invalid,
        "gap_start_utc_ms": first_invalid,
        "gap_end_utc_ms": max(int(item["end_utc_ms"]) for item in first_gaps),
        "affected_symbols": affected_symbols,
        "affected_positions": [
            {"symbol": symbol, "open_position_crosses": True} for symbol in affected_symbols
        ],
        "processed_minute_count": min(
            int(item["processed_minute_count"]) for item in result.metrics
        ),
        "path_kinds": sorted(run.path_kind.value for run in result.runs),
    }


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


@contextmanager
def experiment_temporary_directory(output_root: Path, experiment_id: str):
    temporary = output_root / f".{experiment_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        yield temporary
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def canonical_report_value(value: object) -> object:
    """Quantize binary indicator/statistic floats at the frozen report boundary."""
    if isinstance(value, float):
        return float64_to_decimal_15sig(value)
    if isinstance(value, dict):
        return {key: canonical_report_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(canonical_report_value(item) for item in value)
    return value


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _fill_economic_signature(fill: object) -> tuple[object, ...]:
    return (
        fill.symbol,
        _enum_value(fill.side),
        _enum_value(fill.action),
        fill.event_time_utc_ms,
        fill.quantity,
        fill.fill_price,
        fill.fee,
        _enum_value(fill.selected_exit_reason),
        tuple(_enum_value(item) for item in fill.matched_exit_reasons),
    )


def _trade_economic_signature(trade: object) -> tuple[object, ...]:
    return (
        trade.symbol,
        _enum_value(trade.side),
        trade.entry_time_utc_ms,
        trade.exit_time_utc_ms,
        trade.entry_price,
        trade.exit_price,
        trade.quantity,
        trade.entry_fee,
        trade.exit_fee,
        trade.funding,
        trade.gross_pnl,
        trade.net_pnl,
        _enum_value(trade.exit_reason),
    )


def _protective_counts(fills: tuple[object, ...]) -> dict[str, int]:
    counts = {"STOP_LOSS": 0, "TAKE_PROFIT": 0, "LIQUIDATION": 0}
    for fill in fills:
        suffix = str(fill.plan_id).rsplit(":", 1)[-1]
        if suffix in counts:
            counts[suffix] += 1
    return counts


def _reconcile_authorities(
    native_runs: tuple[object, ...],
    aggregated_runs: tuple[object, ...],
    native_metrics: tuple[dict[str, object], ...] | list[dict[str, object]],
    aggregated_metrics: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    native_by_path = {run.path_kind.value: run for run in native_runs}
    aggregated_by_path = {run.path_kind.value: run for run in aggregated_runs}
    native_metric = {item["path_kind"]: item for item in native_metrics}
    aggregated_metric = {item["path_kind"]: item for item in aggregated_metrics}
    output = {}
    for path in sorted(native_by_path):
        native = native_by_path[path]
        aggregated = aggregated_by_path[path]
        native_fill_signature = tuple(_fill_economic_signature(item) for item in native.fills)
        aggregated_fill_signature = tuple(
            _fill_economic_signature(item) for item in aggregated.fills
        )
        native_trade_signature = tuple(_trade_economic_signature(item) for item in native.trades)
        aggregated_trade_signature = tuple(
            _trade_economic_signature(item) for item in aggregated.trades
        )
        metrics_match = all(
            native_metric[path][name] == aggregated_metric[path][name]
            for name in ("net_return", "maximum_drawdown")
        )
        economic_match = (
            native_fill_signature == aggregated_fill_signature
            and native_trade_signature == aggregated_trade_signature
            and metrics_match
        )
        output[path] = {
            "economic_outputs_match": economic_match,
            "native_trade_count": len(native.trades),
            "aggregated_trade_count": len(aggregated.trades),
            "trade_count_difference": len(aggregated.trades) - len(native.trades),
            "native_fill_count": len(native.fills),
            "aggregated_fill_count": len(aggregated.fills),
            "fill_count_difference": len(aggregated.fills) - len(native.fills),
            "native_protective_exit_counts": _protective_counts(native.fills),
            "aggregated_protective_exit_counts": _protective_counts(aggregated.fills),
            "native_net_return": native_metric[path]["net_return"],
            "aggregated_net_return": aggregated_metric[path]["net_return"],
            "net_return_difference": Decimal(str(aggregated_metric[path]["net_return"]))
            - Decimal(str(native_metric[path]["net_return"])),
            "native_maximum_drawdown": native_metric[path]["maximum_drawdown"],
            "aggregated_maximum_drawdown": aggregated_metric[path]["maximum_drawdown"],
            "maximum_drawdown_difference": Decimal(str(aggregated_metric[path]["maximum_drawdown"]))
            - Decimal(str(native_metric[path]["maximum_drawdown"])),
            "affected_native_trade_ids": (
                () if economic_match else tuple(item.origin_candidate_id for item in native.trades)
            ),
            "affected_aggregated_trade_ids": (
                ()
                if economic_match
                else tuple(item.origin_candidate_id for item in aggregated.trades)
            ),
            "affected_native_fill_ids": (
                () if economic_match else tuple(item.fill_id for item in native.fills)
            ),
            "affected_aggregated_fill_ids": (
                () if economic_match else tuple(item.fill_id for item in aggregated.fills)
            ),
        }
    return output


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
    trends: tuple[object, ...],
) -> tuple[
    tuple[tuple[str, int, Decimal], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, tuple[int, ...]], ...],
    tuple[tuple[str, int, Decimal], ...],
]:
    entry_targets = tuple(
        sorted((item.symbol, item.decision_time_utc_ms + 1 + 60_000) for item in candidates)
    )
    required = set(_required_evidence_targets(candidates, trends, split))
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


def _required_evidence_targets(
    candidates: tuple[object, ...], trends: tuple[object, ...], split: Split
) -> tuple[tuple[str, int], ...]:
    entry_targets = tuple(
        sorted((item.symbol, item.decision_time_utc_ms + 1 + 60_000) for item in candidates)
    )
    required = set(entry_targets)
    for symbol, entry_time in entry_targets:
        time_exit = entry_time + 48 * 60 * 60 * 1000 + 120_000
        if time_exit <= split.end_exit_open_utc_ms:
            required.add((symbol, time_exit))
    for item in trends:
        target = item.decision_time_utc_ms + 1 + 60_000
        if split.start_utc_ms <= target <= split.end_exit_open_utc_ms:
            required.add((item.symbol, target))
    for symbol in SUPPORTED_SYMBOLS:
        required.add((symbol, split.end_exit_open_utc_ms))
    return tuple(sorted(required))


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
    progress_callback: Callable[[int, int], None] | None = None,
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
        progress_callback=progress_callback,
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
    max_workers: int = 1,
    hard_timeout_seconds: float = 21_600,
    no_progress_timeout_seconds: float | None = None,
    diagnostics_root: Path | None = None,
    known_diagnostic_gap_report: Path | None = None,
) -> Path:
    with exclusive_output_lock(output_root):
        existing_temporaries = {
            path.resolve() for path in output_root.glob(".*.tmp") if path.is_dir()
        }
        try:
            return _run_baseline_evaluation_locked(
                root=root,
                output_root=output_root,
                code_commit=code_commit,
                max_workers=max_workers,
                hard_timeout_seconds=hard_timeout_seconds,
                no_progress_timeout_seconds=no_progress_timeout_seconds,
                diagnostics_root=diagnostics_root,
                known_diagnostic_gap_report=known_diagnostic_gap_report,
            )
        except BaseException:
            for path in output_root.glob(".*.tmp"):
                if path.is_dir() and path.resolve() not in existing_temporaries:
                    shutil.rmtree(path)
            raise


def _run_baseline_evaluation_locked(
    *,
    root: Path,
    output_root: Path,
    code_commit: str,
    max_workers: int,
    hard_timeout_seconds: float,
    no_progress_timeout_seconds: float | None,
    diagnostics_root: Path | None,
    known_diagnostic_gap_report: Path | None,
) -> Path:
    started_monotonic = time.perf_counter()
    approval = verify_data_approval_manifest(root / "data_approval_manifest_v1.json")
    diagnostic_statuses: dict[str, dict[str, object]] = {}
    diagnostic_evidence = None
    if known_diagnostic_gap_report is not None:
        diagnostic_statuses, diagnostic_evidence = load_known_training_gap_evidence(
            known_diagnostic_gap_report,
            approved_data_bundle_hash=approval.manifest["hybrid_historical_data_bundle_hash"],
        )
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
        "known_diagnostic_gap_evidence": diagnostic_evidence,
    }
    all_metrics: dict[str, Any] = {}
    all_runs: dict[tuple[str, str, str], tuple[object, ...]] = {}
    candidates_meta = {}
    benchmarks = {}
    tasks = []
    training_start = splits[0].start_utc_ms
    base = Scenario("BASE_1X", Decimal("1"), Decimal("1"))

    def prepare_base_task(split: Split, authority: str) -> EvaluationTask:
        candidates, trends, counts, daily = _load_candidates(
            root,
            split,
            authority,
            training_start,
            code_commit,
            approval.manifest["dependency_lock_hash"],
        )
        evidence_data = _market_evidence(root, split, candidates, trends)
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
        return EvaluationTask(
            key=f"{split.name}:{authority}:BASE_1X",
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

    split_by_name = {split.name: split for split in splits}
    oos = split_by_name["OOS"]
    oos_native = prepare_base_task(oos, "NATIVE_PRIMARY")
    tasks.append(oos_native)
    stresses = (
        Scenario("COMBINED_2X", Decimal("2"), Decimal("2")),
        Scenario("FEE_SLIPPAGE_3X", Decimal("1"), Decimal("1"), Decimal("3"), Decimal("3")),
        Scenario("FUNDING_2X", Decimal("1"), Decimal("2")),
    )
    for scenario in stresses:
        tasks.append(
            EvaluationTask(
                key=f"OOS:NATIVE_PRIMARY:{scenario.name}",
                root=root,
                split=oos,
                authority="NATIVE_PRIMARY",
                scenario=scenario,
                candidates=oos_native.candidates,
                trends=oos_native.trends,
                evidence_data=oos_native.evidence_data,
                experiment_id=experiment_id,
                approval_hash=approval.manifest_hash,
                code_commit=code_commit,
                dependency_lock_hash=approval.manifest["dependency_lock_hash"],
            )
        )
    tasks.append(prepare_base_task(oos, "AGGREGATED_AUDIT_SENSITIVITY"))
    validation = split_by_name["VALIDATION"]
    tasks.extend(prepare_base_task(validation, authority) for authority in AUTHORITIES)
    if not diagnostic_statuses:
        training = split_by_name["TRAINING"]
        tasks.extend(prepare_base_task(training, authority) for authority in AUTHORITIES)
    expected_task_keys = tuple(key for key in formal_task_keys() if key not in diagnostic_statuses)
    if tuple(task.key for task in tasks) != expected_task_keys:
        raise AssertionError("formal task registry differs from frozen order")
    batch = run_prioritized_task_phases(
        tuple(tasks),
        max_workers=max_workers,
        hard_timeout_seconds=hard_timeout_seconds,
        no_progress_timeout_seconds=no_progress_timeout_seconds,
    )
    cost_stress = {}
    for result in batch.results:
        disposition = assess_formal_task_result(result)
        if disposition.status is TaskDisposition.DIAGNOSTIC_DATA_GAP:
            diagnostic_statuses[result.key] = diagnostic_gap_record(result)
            continue
        split_name, authority, scenario_name = result.key.split(":")
        all_runs[(split_name, authority, scenario_name)] = result.runs
        if scenario_name == "BASE_1X":
            all_metrics[result.key] = result.metrics
        else:
            cost_stress[scenario_name] = result.metrics
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
    aggregated_metrics["authority_reconciliation"] = {
        split.name: _reconcile_authorities(
            all_runs[(split.name, "NATIVE_PRIMARY", "BASE_1X")],
            all_runs[(split.name, "AGGREGATED_AUDIT_SENSITIVITY", "BASE_1X")],
            all_metrics[f"{split.name}:NATIVE_PRIMARY:BASE_1X"],
            all_metrics[f"{split.name}:AGGREGATED_AUDIT_SENSITIVITY:BASE_1X"],
        )
        for split in splits
        if (split.name, "NATIVE_PRIMARY", "BASE_1X") in all_runs
        and (split.name, "AGGREGATED_AUDIT_SENSITIVITY", "BASE_1X") in all_runs
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
        "diagnostic_status": diagnostic_statuses,
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
        "diagnostic_status.json": diagnostic_statuses,
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
    diagnostics_base = diagnostics_root or output_root.parent / "research_2d_diagnostics"
    diagnostics_directory = diagnostics_base / experiment_id
    diagnostics_directory.mkdir(parents=True, exist_ok=True)
    run_id = f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex}"
    diagnostics = {
        "schema_version": "RESEARCH_2D_RUNTIME_DIAGNOSTICS_V1",
        "computational_experiment_id": experiment_id,
        "run_id": run_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "duration_seconds": time.perf_counter() - started_monotonic,
        "parent_pid": os.getpid(),
        "worker_count": max_workers,
        "multiprocessing_start_method": batch.multiprocessing_start_method,
        "parent_peak_rss_bytes": batch.parent_peak_rss_bytes,
        "aggregate_worker_peak_rss_bytes": batch.aggregate_worker_peak_rss_bytes,
        "tasks": {
            result.key: {
                "worker_pid": result.worker_pid,
                "worker_peak_rss_bytes": result.worker_peak_rss_bytes,
                "payload_pickle_bytes": result.payload_pickle_bytes,
                "result_pickle_bytes": result.result_pickle_bytes,
            }
            for result in batch.results
        },
        "heartbeat_count": len(batch.heartbeats),
    }
    _atomic_text(
        diagnostics_directory / f"{run_id}.json",
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return final
