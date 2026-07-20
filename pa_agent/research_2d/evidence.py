from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.contracts import approximated_contract_rule
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import (
    ApproximationDirection,
    ContractRuleReviewStatus,
    ResearchStage,
)
from pa_agent.research_backtest.domain.funding import (
    covered_funding_risk_config,
    funding_schedule_snapshot,
    settlement_window,
)
from pa_agent.research_backtest.domain.market_inputs import (
    target_event_watermark,
    target_minute_open_snapshot,
)
from pa_agent.research_backtest.simulation.evidence import (
    SimulationEvidenceCatalog,
    make_simulation_evidence_catalog,
)
from pa_agent.research_backtest.simulation.liquidation import MaintenanceEvidence

SYMBOL_RULES = {
    "BTCUSDT": (Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("50"), 1, 3),
    "ETHUSDT": (Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("20"), 2, 3),
}
CURRENT_RULE_EVIDENCE_TIME_UTC_MS = 1_784_398_693_948
CURRENT_RULE_SOURCE_HASH = "a6837f3fd1fd458f11b12d55e4e2797c5f01c9b4f8fe8f5c80d4317f170d9d0b"
CONTRACT_RULE_VERSION = "APPROXIMATED_CURRENT_RULES_V1"
MAINTENANCE_VERSION = "APPROXIMATED_MAINTENANCE_MODEL_V1"


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    split_start_utc_ms: int
    split_end_exit_open_utc_ms: int
    target_prices: tuple[tuple[str, int, Decimal], ...]
    required_targets: tuple[tuple[str, int], ...]
    entry_targets: tuple[tuple[str, int], ...]
    funding_times: tuple[tuple[str, tuple[int, ...]], ...]
    funding_rate_caps: tuple[tuple[str, int, Decimal], ...]
    fee_rate: Decimal
    slippage_rates: tuple[tuple[str, Decimal], ...]
    cost_stress_multiplier: Decimal
    funding_stress_multiplier: Decimal
    source_manifest_hash: str
    code_commit: str
    dependency_lock_hash: str


def build_evidence_catalog(request: EvidenceRequest) -> SimulationEvidenceCatalog:
    target_prices = tuple(sorted(set(request.target_prices)))
    target_keys = {(symbol, time) for symbol, time, _ in target_prices}
    entry_targets = tuple(sorted(set(request.entry_targets)))
    if any(item not in target_keys for item in entry_targets):
        # Missing opens remain absent evidence and therefore fail closed in frozen 2C.
        pass
    targets = tuple(
        target_minute_open_snapshot(
            symbol=symbol,
            open_time_utc_ms=time,
            open_price=price,
            source_stream_version="BINANCE_ARCHIVE_TRADE_1M_V1",
            code_commit=request.code_commit,
            dependency_lock_hash=request.dependency_lock_hash,
        )
        for symbol, time, price in target_prices
    )
    all_target_keys = tuple(sorted(set(request.required_targets) | set(entry_targets)))
    watermarks = tuple(
        target_event_watermark(
            symbol=symbol,
            target_open_time_utc_ms=time,
            event_watermark_time_utc_ms=time,
            watermark_source_event_id=f"approved-trade-minute-{symbol}-{time}",
            watermark_source_stream_version="BINANCE_ARCHIVE_TRADE_1M_V1",
            code_commit=request.code_commit,
            dependency_lock_hash=request.dependency_lock_hash,
        )
        for symbol, time in all_target_keys
    )
    contracts = []
    for symbol, time in all_target_keys:
        tick, step, min_qty, min_notional, price_precision, quantity_precision = SYMBOL_RULES[
            symbol
        ]
        contracts.append(
            approximated_contract_rule(
                symbol=symbol,
                query_time_utc_ms=time,
                source_kind="BINANCE_CURRENT_EXCHANGE_INFO",
                source_uri_or_archive_id="/fapi/v1/exchangeInfo:2026-07-19",
                source_content_hash=CURRENT_RULE_SOURCE_HASH,
                effective_from_utc_ms=request.split_start_utc_ms,
                effective_to_utc_ms=request.split_end_exit_open_utc_ms + 60_000,
                rule_version=CONTRACT_RULE_VERSION,
                tick_size=tick,
                step_size=step,
                min_qty=min_qty,
                min_notional=min_notional,
                quantity_precision_audit=quantity_precision,
                price_precision_audit=price_precision,
                evidence_manifest_hash=request.source_manifest_hash,
                review_status=ContractRuleReviewStatus.APPROVED_HINDSIGHT_DIAGNOSTIC,
                approximation_method="CURRENT_RULE_HINDSIGHT_DIAGNOSTIC",
                approximation_distance_ms=CURRENT_RULE_EVIDENCE_TIME_UTC_MS - time,
                evidence_time_utc_ms=CURRENT_RULE_EVIDENCE_TIME_UTC_MS,
                approximation_direction=(ApproximationDirection.HINDSIGHT_DIAGNOSTIC_APPROXIMATION),
            )
        )
    slippage = dict(request.slippage_rates)
    costs = tuple(
        cost_model_snapshot(
            symbol=symbol,
            fee_rate=request.fee_rate,
            slippage_rate=slippage[symbol],
            stress_multiplier=request.cost_stress_multiplier,
        )
        for symbol in sorted(SYMBOL_RULES)
    )
    times_by_symbol = dict(request.funding_times)
    schedules = tuple(
        funding_schedule_snapshot(
            symbol=symbol,
            schedule_version="BINANCE_ARCHIVE_ACTUAL_FUNDING_WINDOWS_V1",
            effective_from_utc_ms=request.split_start_utc_ms,
            effective_to_utc_ms=request.split_end_exit_open_utc_ms + 60_000,
            settlement_windows=tuple(
                settlement_window(time, time, time)
                for time in times_by_symbol[symbol]
                if request.split_start_utc_ms <= time <= request.split_end_exit_open_utc_ms
            ),
            window_tolerance_ms=0,
            source_manifest_hash=request.source_manifest_hash,
            code_commit=request.code_commit,
            dependency_lock_hash=request.dependency_lock_hash,
        )
        for symbol in sorted(SYMBOL_RULES)
    )
    caps = {(symbol, time): cap for symbol, time, cap in request.funding_rate_caps}
    risks = tuple(
        covered_funding_risk_config(
            symbol=symbol,
            target_time_utc_ms=time,
            adverse_rate_cap=caps[(symbol, time)] * request.funding_stress_multiplier,
            effective_from_utc_ms=request.split_start_utc_ms,
            effective_to_utc_ms=request.split_end_exit_open_utc_ms + 60_000,
            source_kind="BINANCE_ARCHIVE_PRIOR_OBSERVED_MAX",
            source_manifest_hash=request.source_manifest_hash,
            verification_mode="APPROXIMATED",
            stress_multiplier=request.funding_stress_multiplier,
            watermark="BASELINE_ASSUMPTION_NOT_VERIFIED",
            evidence_time_utc_ms=time,
            code_commit=request.code_commit,
            dependency_lock_hash=request.dependency_lock_hash,
        )
        for symbol, time in entry_targets
    )
    maintenance = tuple(
        MaintenanceEvidence(
            symbol=symbol,
            effective_start_utc_ms=request.split_start_utc_ms,
            effective_end_utc_ms=request.split_end_exit_open_utc_ms + 60_000,
            notional_floor=Decimal("0"),
            notional_cap=Decimal("1000000000"),
            maintenance_margin_rate=Decimal("0.005"),
            source_hash=canonical_sha256(
                {"version": MAINTENANCE_VERSION, "symbol": symbol, "rate": "0.005"}
            ),
            mode="APPROXIMATED",
            version=MAINTENANCE_VERSION,
        )
        for symbol in sorted(SYMBOL_RULES)
    )
    return make_simulation_evidence_catalog(
        target_opens=targets,
        watermarks=watermarks,
        contracts=tuple(contracts),
        costs=costs,
        funding_schedules=schedules,
        funding_risks=risks,
        maintenance=maintenance,
        stage=ResearchStage.BACKTEST,
        split_start_utc_ms=request.split_start_utc_ms,
        split_end_utc_ms=request.split_end_exit_open_utc_ms,
        code_commit=request.code_commit,
        dependency_lock_hash=request.dependency_lock_hash,
    )
