from __future__ import annotations

from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import (
    account_evidence_bundle,
    account_evidence_records,
    experiment_state_evidence,
    make_account_planning_snapshot,
    wallet_ledger_evidence,
)
from pa_agent.research_backtest.domain.batches import (
    expected_intent_ref,
    portfolio_batch_completeness_snapshot,
    portfolio_planning_batch,
    resolution_ref,
)
from pa_agent.research_backtest.domain.candidates import strategy_candidate
from pa_agent.research_backtest.domain.config import execution_time_config
from pa_agent.research_backtest.domain.contracts import verified_contract_rule
from pa_agent.research_backtest.domain.costs import cost_model_snapshot
from pa_agent.research_backtest.domain.enums import (
    ExperimentState,
    MarketReason,
    MarketView,
    ResolutionKind,
    TrendState,
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
from pa_agent.research_backtest.planning.funding import count_funding_events
from pa_agent.research_backtest.planning.intents import make_entry_intent
from pa_agent.research_backtest.planning.portfolio import scale_portfolio
from pa_agent.research_backtest.planning.sizing import SizingInputs, position_sizing

SHA = "a" * 64
LOCK = "b" * 64
COMMIT = "c" * 40
DECISION_TIME = 14_400_000 - 1
TARGET_TIME = 14_460_000
MAXIMUM_EXIT_TIME = TARGET_TIME + 172_800_000


def complete_entry_inputs(*, state: ExperimentState = ExperimentState.RUNNING):
    candidate = strategy_candidate(
        symbol="BTCUSDT",
        decision_time_utc_ms=DECISION_TIME,
        decision_bar_open_time_utc_ms=0,
        market_view=MarketView.LONG,
        market_reason=MarketReason.BULL_DONCHIAN_BREAKOUT,
        decision_close=Decimal("121"),
        daily_close=Decimal("110"),
        trend_state=TrendState.BULL,
        ema50_daily=Decimal("105"),
        ema200_daily=Decimal("100"),
        atr14_4h=Decimal("10"),
        donchian_high_previous_20=Decimal("120"),
        donchian_low_previous_20=Decimal("80"),
        decision_visible_input_hash=SHA,
        indicator_config_hash="d" * 64,
        strategy_config_hash="e" * 64,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    config = execution_time_config(entry_delay_minutes=1, exit_delay_minutes=1)
    intent = make_entry_intent(
        candidate,
        config,
        computational_experiment_id="f" * 64,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    target_open = target_minute_open_snapshot(
        symbol="BTCUSDT",
        open_time_utc_ms=TARGET_TIME,
        open_price=Decimal("121"),
        source_stream_version="BINANCE_TRADE_OPEN_EVENT_V1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    watermark = target_event_watermark(
        symbol="BTCUSDT",
        target_open_time_utc_ms=TARGET_TIME,
        event_watermark_time_utc_ms=TARGET_TIME,
        watermark_source_event_id="watermark-event-1",
        watermark_source_stream_version="BINANCE_TRADE_WATERMARK_V1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    contract = verified_contract_rule(
        symbol="BTCUSDT",
        query_time_utc_ms=TARGET_TIME,
        source_kind="BINANCE_ARCHIVE",
        source_uri_or_archive_id="rules/btc/v1",
        source_content_hash=SHA,
        effective_from_utc_ms=0,
        effective_to_utc_ms=MAXIMUM_EXIT_TIME + 1,
        rule_version="BTCUSDT_RULE_V1",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        quantity_precision_audit=3,
        price_precision_audit=1,
        evidence_manifest_hash="1" * 64,
    )
    cost = cost_model_snapshot(
        symbol="BTCUSDT",
        fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stress_multiplier=Decimal("1"),
    )
    windows = tuple(
        settlement_window(time - 1_000, time, time + 1_000)
        for time in range(28_800_000, 172_800_001, 28_800_000)
    )
    schedule = funding_schedule_snapshot(
        symbol="BTCUSDT",
        schedule_version="BINANCE_EXPLICIT_WINDOWS_V1",
        effective_from_utc_ms=0,
        effective_to_utc_ms=MAXIMUM_EXIT_TIME + 1,
        settlement_windows=windows,
        window_tolerance_ms=1_000,
        source_manifest_hash="2" * 64,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    funding_risk = covered_funding_risk_config(
        symbol="BTCUSDT",
        target_time_utc_ms=TARGET_TIME,
        adverse_rate_cap=Decimal("0.0001"),
        effective_from_utc_ms=0,
        effective_to_utc_ms=MAXIMUM_EXIT_TIME + 1,
        source_kind="REVIEWED_BASELINE",
        source_manifest_hash="3" * 64,
        verification_mode="VERIFIED",
        stress_multiplier=Decimal("1"),
        watermark="VERIFIED",
        evidence_time_utc_ms=TARGET_TIME,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    records = account_evidence_records(
        wallet=wallet_ledger_evidence(
            wallet_balance=Decimal("10000"),
            locked_initial_margin=Decimal("0"),
            locked_fee_reserve=Decimal("0"),
            locked_funding_reserve=Decimal("0"),
        ),
        valuations=(),
        positions=(),
        open_risks=(),
        pending_plans=(),
        experiment_state=experiment_state_evidence(event_time_utc_ms=TARGET_TIME, state=state),
    )
    bundle = account_evidence_bundle(
        records,
        event_time_utc_ms=TARGET_TIME,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    account = make_account_planning_snapshot(bundle, records, eligible_time_utc_ms=TARGET_TIME)
    event_count = count_funding_events(TARGET_TIME, MAXIMUM_EXIT_TIME, schedule)
    sizing = position_sizing(
        SizingInputs(
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            reference_price=target_open.open_price,
            atr=candidate.atr14_4h,
            contract=contract,
            cost=cost,
            funding_risk=funding_risk,
            funding_event_upper_bound=event_count,
            account=account,
        )
    )
    expected = (expected_intent_ref(intent.intent_id, intent.symbol, TARGET_TIME),)
    resolutions = (
        resolution_ref(
            intent.intent_id,
            intent.symbol,
            ResolutionKind.SIZING_RESULT,
            sizing.result_id,
            sizing.result_content_hash,
        ),
    )
    completeness = portfolio_batch_completeness_snapshot(
        expected,
        resolutions,
        completeness_event_time_utc_ms=TARGET_TIME,
        source_event_id="complete-event-1",
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    batch = portfolio_planning_batch(
        completeness,
        account,
        target_open_snapshot_ids=(target_open.snapshot_id,),
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
    scaling = scale_portfolio(
        batch,
        account,
        (sizing,),
        {sizing.result_id: contract},
        (target_open.snapshot_content_hash,),
    )
    accepted = scaling.item_results[0]
    from pa_agent.research_backtest.planning.factory import EntryPlanningInputs

    return EntryPlanningInputs(
        candidate=candidate,
        intent=intent,
        target_open=target_open,
        watermark=watermark,
        contract=contract,
        cost=cost,
        funding_schedule=schedule,
        funding_risk=funding_risk,
        account=account,
        completeness=completeness,
        batch=batch,
        sizing=sizing,
        scaling=scaling,
        accepted_item=accepted,
        split_start_utc_ms=0,
        split_end_utc_ms=MAXIMUM_EXIT_TIME + 1,
        code_commit=COMMIT,
        dependency_lock_hash=LOCK,
    )
