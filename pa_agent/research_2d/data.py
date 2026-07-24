from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from pa_agent.research_backtest.domain.candidates import StrategyCandidate, strategy_candidate
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import MarketView, TrendState
from pa_agent.research_backtest.domain.failures import ValidationFailure
from pa_agent.research_backtest.domain.validation import VisibleValidationState
from pa_agent.research_backtest.indicators.atr import wilder_atr
from pa_agent.research_backtest.indicators.donchian import previous_donchian
from pa_agent.research_backtest.indicators.ema import ema
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig
from pa_agent.research_backtest.simulation.funding import FundingRecord
from pa_agent.research_backtest.simulation.inputs import MinuteBar, MinuteInputSlice
from pa_agent.research_backtest.simulation.planning import TrendEvidence
from pa_agent.research_backtest.strategy.btc_eth_pa_v1 import classify_market
from pa_agent.research_backtest.strategy.candidate_factory import (
    INDICATOR_CONFIG_HASH,
    STRATEGY_CONFIG_HASH,
    build_candidate,
)
from pa_agent.research_backtest.strategy.pre_roll import select_exact_pre_roll
from pa_agent.research_backtest.versions import (
    ATR_VERSION,
    DECISION_VISIBLE_INPUT_VERSION,
    DONCHIAN_VERSION,
    EMA_VERSION,
    INDICATOR_CONFIG_VERSION,
    NUMERIC_BOUNDARY_VERSION,
    PRE_ROLL_POLICY_VERSION,
    assert_runtime_lock,
)
from pa_agent.research_data.models import Kline

SUPPORTED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
STREAM_INTERVAL = {
    "trade_1m": ("trade", "1m"),
    "mark_1m": ("mark", "1m"),
    "index_1m": ("index", "1m"),
    "trade_4h": ("trade", "4h"),
    "trade_1d": ("trade", "1d"),
}
INTERVAL_MINUTES = {"4h": 240, "1d": 1_440}


class CanonicalDataError(ValueError):
    """Canonical historical input violates a frozen data invariant."""


@dataclass(frozen=True, slots=True)
class CandidateStream:
    candidates: tuple[StrategyCandidate, ...]
    failures: tuple[ValidationFailure, ...]


@dataclass(frozen=True, slots=True)
class ActionableCandidateStream:
    candidates: tuple[StrategyCandidate, ...]
    market_view_counts: dict[str, int]
    trend_evidence: tuple[TrendEvidence, ...]


@dataclass(frozen=True, slots=True)
class StrategyBars:
    daily: tuple[Kline, ...]
    four_hour: tuple[Kline, ...]


def load_strategy_bars(
    root: Path,
    *,
    symbol: str,
    authority: str,
    start_utc_ms: int,
    end_utc_ms: int,
) -> StrategyBars:
    if authority == "NATIVE_PRIMARY":
        daily = tuple(
            kline_from_record(item)
            for item in iter_canonical_records(root, symbol, "trade_1d", start_utc_ms, end_utc_ms)
        )
        four_hour = tuple(
            kline_from_record(item)
            for item in iter_canonical_records(root, symbol, "trade_4h", start_utc_ms, end_utc_ms)
        )
    elif authority == "AGGREGATED_SENSITIVITY":
        daily = aggregate_trade_klines(
            iter_canonical_records(root, symbol, "trade_1m", start_utc_ms, end_utc_ms),
            interval="1d",
        )
        four_hour = aggregate_trade_klines(
            iter_canonical_records(root, symbol, "trade_1m", start_utc_ms, end_utc_ms),
            interval="4h",
        )
    else:
        raise CanonicalDataError("unsupported strategy authority")
    return StrategyBars(daily=daily, four_hour=four_hour)


def _next_or_none(iterator: Iterator[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def iter_joint_minute_slices(
    root: Path,
    *,
    start_utc_ms: int,
    end_utc_ms: int,
    funding_multiplier: Decimal,
    trend_evidence: Iterable[TrendEvidence] = (),
) -> Iterator[MinuteInputSlice]:
    """Stream exact UTC minutes without synthesizing any absent market record."""
    streams: dict[tuple[str, str], Iterator[dict[str, Any]]] = {}
    current: dict[tuple[str, str], dict[str, Any] | None] = {}
    for symbol in SUPPORTED_SYMBOLS:
        for stream in ("trade_1m", "mark_1m", "funding"):
            iterator = iter_canonical_records(root, symbol, stream, start_utc_ms, end_utc_ms)
            streams[(symbol, stream)] = iterator
            current[(symbol, stream)] = _next_or_none(iterator)
    trend_by_time: dict[int, list[TrendEvidence]] = {}
    for item in trend_evidence:
        minute_open = item.decision_time_utc_ms + 1 - 60_000
        trend_by_time.setdefault(minute_open, []).append(item)
    for minute_open in range(start_utc_ms, end_utc_ms + 1, 60_000):
        trades: list[MinuteBar] = []
        marks: list[MinuteBar] = []
        funding: list[FundingRecord] = []
        expected_funding: list[str] = []
        mark_by_symbol: dict[str, Decimal] = {}
        for symbol in SUPPORTED_SYMBOLS:
            for stream, destination in (("trade_1m", trades), ("mark_1m", marks)):
                key = (symbol, stream)
                row = current[key]
                if row is not None and int(row["open_time_utc_ms"]) == minute_open:
                    bar = minute_bar_from_record(row)
                    destination.append(bar)
                    if stream == "mark_1m":
                        mark_by_symbol[symbol] = bar.open
                    current[key] = _next_or_none(streams[key])
            key = (symbol, "funding")
            row = current[key]
            while (
                row is not None
                and int(row["funding_time_utc_ms"]) // 60_000 * 60_000 == minute_open
            ):
                expected_funding.append(symbol)
                if symbol in mark_by_symbol:
                    funding.append(
                        funding_record(
                            row,
                            mark_price=mark_by_symbol[symbol],
                            multiplier=funding_multiplier,
                        )
                    )
                current[key] = _next_or_none(streams[key])
                row = current[key]
        yield MinuteInputSlice(
            minute_open_utc_ms=minute_open,
            trade_bars=tuple(sorted(trades, key=lambda item: item.symbol)),
            mark_bars=tuple(sorted(marks, key=lambda item: item.symbol)),
            funding_records=tuple(sorted(funding, key=lambda item: item.symbol)),
            due_intents=(),
            funding_expected=bool(expected_funding),
            funding_expected_symbols=tuple(sorted(set(expected_funding))),
            trend_evidence=tuple(
                sorted(trend_by_time.get(minute_open, ()), key=lambda item: item.symbol)
            ),
        )


def _visible_hash_from_serialized(
    *,
    symbol: str,
    decision_time_utc_ms: int,
    training_start_utc_ms: int,
    daily_json: tuple[str, ...],
    four_hour_json: tuple[str, ...],
    validation_state: VisibleValidationState,
) -> str:
    payload = (
        '{"daily_bars":['
        + ",".join(daily_json)
        + '],"decision_time_utc_ms":'
        + str(decision_time_utc_ms)
        + ',"decision_visible_input_version":'
        + canonical_dumps(DECISION_VISIBLE_INPUT_VERSION)
        + ',"four_hour_bars":['
        + ",".join(four_hour_json)
        + '],"indicator_versions":'
        + canonical_dumps(
            {
                "atr": ATR_VERSION,
                "config": INDICATOR_CONFIG_VERSION,
                "donchian": DONCHIAN_VERSION,
                "ema": EMA_VERSION,
                "numeric_boundary": NUMERIC_BOUNDARY_VERSION,
            }
        )
        + ',"pre_roll_policy_version":'
        + canonical_dumps(PRE_ROLL_POLICY_VERSION)
        + ',"symbol":'
        + canonical_dumps(symbol)
        + ',"training_start_utc_ms":'
        + str(training_start_utc_ms)
        + ',"visible_validation_state":'
        + canonical_dumps(asdict(validation_state))
        + "}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fast_decision_visible_input_hash(
    *,
    symbol: str,
    decision_time_utc_ms: int,
    training_start_utc_ms: int,
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    validation_state: VisibleValidationState,
) -> str:
    daily = tuple(
        canonical_dumps(bar)
        for bar in sorted(daily_bars, key=lambda item: item.open_time_utc_ms)
        if bar.close_time_utc_ms <= decision_time_utc_ms
    )
    four_hour = tuple(
        canonical_dumps(bar)
        for bar in sorted(four_hour_bars, key=lambda item: item.open_time_utc_ms)
        if bar.close_time_utc_ms <= decision_time_utc_ms
    )
    return _visible_hash_from_serialized(
        symbol=symbol,
        decision_time_utc_ms=decision_time_utc_ms,
        training_start_utc_ms=training_start_utc_ms,
        daily_json=daily,
        four_hour_json=four_hour,
        validation_state=validation_state,
    )


def iter_canonical_records(
    root: Path,
    symbol: str,
    stream: str,
    start_utc_ms: int,
    end_utc_ms: int,
) -> Iterator[dict[str, Any]]:
    if symbol not in SUPPORTED_SYMBOLS:
        raise CanonicalDataError(f"unsupported symbol {symbol}")
    if start_utc_ms < 0 or end_utc_ms < start_utc_ms:
        raise CanonicalDataError("invalid UTC interval")
    directory = root / "data" / "canonical" / symbol / stream
    previous: int | None = None
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CanonicalDataError(f"invalid JSON at {path}:{line_number}") from exc
                timestamp = int(
                    record.get("open_time_utc_ms", record.get("funding_time_utc_ms", -1))
                )
                if previous is not None and timestamp <= previous:
                    raise CanonicalDataError(
                        f"{symbol}/{stream} timestamps must be strictly increasing"
                    )
                previous = timestamp
                if timestamp < start_utc_ms:
                    continue
                if timestamp > end_utc_ms:
                    return
                yield record


def _decimal(record: Mapping[str, Any], field: str) -> Decimal:
    try:
        value = Decimal(str(record[field]))
    except (KeyError, ValueError) as exc:
        raise CanonicalDataError(f"invalid Decimal field {field}") from exc
    if not value.is_finite():
        raise CanonicalDataError(f"non-finite Decimal field {field}")
    return value


def kline_from_record(record: Mapping[str, Any]) -> Kline:
    if record.get("is_closed") is not True:
        raise CanonicalDataError("UNCLOSED_BAR")
    try:
        return Kline(
            source=str(record["source"]),
            stream=str(record["stream"]),
            symbol=str(record["symbol"]),
            interval=str(record["interval"]),
            open_time_utc_ms=int(record["open_time_utc_ms"]),
            close_time_utc_ms=int(record["close_time_utc_ms"]),
            open=_decimal(record, "open"),
            high=_decimal(record, "high"),
            low=_decimal(record, "low"),
            close=_decimal(record, "close"),
            base_volume=_decimal(record, "base_volume"),
            quote_volume=_decimal(record, "quote_volume"),
            trade_count=int(record["trade_count"]),
            taker_buy_base_volume=_decimal(record, "taker_buy_base_volume"),
            taker_buy_quote_volume=_decimal(record, "taker_buy_quote_volume"),
            is_closed=True,
            schema_version=str(record["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CanonicalDataError):
            raise
        raise CanonicalDataError("invalid Canonical Kline record") from exc


def minute_bar_from_record(record: Mapping[str, Any]) -> MinuteBar:
    value = kline_from_record(record)
    if value.interval != "1m":
        raise CanonicalDataError("minute engine input must be a 1m Kline")
    return MinuteBar(
        symbol=value.symbol,
        open_time_utc_ms=value.open_time_utc_ms,
        close_time_utc_ms=value.close_time_utc_ms,
        open=value.open,
        high=value.high,
        low=value.low,
        close=value.close,
        is_closed=value.is_closed,
        content_hash=canonical_sha256(record),
    )


def _aggregate_bucket(rows: list[Kline], interval: str) -> Kline:
    expected = INTERVAL_MINUTES[interval]
    if len(rows) != expected:
        raise CanonicalDataError(f"partial {interval} bucket")
    start = rows[0].open_time_utc_ms
    if start % (expected * 60_000) or any(
        row.open_time_utc_ms != start + index * 60_000 for index, row in enumerate(rows)
    ):
        raise CanonicalDataError(f"non-contiguous {interval} bucket")
    return Kline(
        source="binance_data_vision_1m_aggregate",
        stream="trade",
        symbol=rows[0].symbol,
        interval=interval,
        open_time_utc_ms=start,
        close_time_utc_ms=start + expected * 60_000 - 1,
        open=rows[0].open,
        high=max(row.high for row in rows),
        low=min(row.low for row in rows),
        close=rows[-1].close,
        base_volume=sum((row.base_volume for row in rows), Decimal("0")),
        quote_volume=sum((row.quote_volume for row in rows), Decimal("0")),
        trade_count=sum(row.trade_count for row in rows),
        taker_buy_base_volume=sum((row.taker_buy_base_volume for row in rows), Decimal("0")),
        taker_buy_quote_volume=sum((row.taker_buy_quote_volume for row in rows), Decimal("0")),
        is_closed=True,
    )


def aggregate_trade_klines(
    records: Iterable[Mapping[str, Any]], *, interval: str
) -> tuple[Kline, ...]:
    if interval not in INTERVAL_MINUTES:
        raise CanonicalDataError("aggregate interval must be 4h or 1d")
    width = INTERVAL_MINUTES[interval] * 60_000
    output: list[Kline] = []
    bucket: list[Kline] = []
    bucket_start: int | None = None
    for record in records:
        value = kline_from_record(record)
        if value.stream != "trade" or value.interval != "1m":
            raise CanonicalDataError("aggregation requires trade 1m records")
        current = value.open_time_utc_ms // width * width
        if bucket_start is None:
            bucket_start = current
        if current != bucket_start:
            output.append(_aggregate_bucket(bucket, interval))
            bucket = []
            bucket_start = current
        bucket.append(value)
    if bucket:
        output.append(_aggregate_bucket(bucket, interval))
    return tuple(output)


def funding_record(
    record: Mapping[str, Any], *, mark_price: Decimal, multiplier: Decimal
) -> FundingRecord:
    if not multiplier.is_finite() or multiplier <= 0:
        raise CanonicalDataError("funding multiplier must be positive")
    original_time = int(record["funding_time_utc_ms"])
    normalized_time = original_time // 60_000 * 60_000
    payload = {
        "symbol": str(record["symbol"]),
        "original_funding_time_utc_ms": original_time,
        "funding_time_utc_ms": normalized_time,
        "funding_rate": _decimal(record, "funding_rate") * multiplier,
        "mark_price": mark_price,
        "funding_multiplier": multiplier,
        "boundary_policy": "FUNDING_TIMESTAMP_FLOOR_TO_UTC_MINUTE_V1",
    }
    digest = canonical_sha256(payload)
    return FundingRecord(
        record_id=f"funding_{digest[:24]}",
        symbol=payload["symbol"],
        funding_time_utc_ms=normalized_time,
        funding_rate=payload["funding_rate"],
        mark_price=mark_price,
        content_hash=digest,
    )


def build_candidate_stream(
    *,
    symbol: str,
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    training_start_utc_ms: int,
    decision_start_utc_ms: int,
    decision_end_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> CandidateStream:
    daily = tuple(daily_bars)
    four_hour = tuple(four_hour_bars)
    candidates: list[StrategyCandidate] = []
    failures: list[ValidationFailure] = []
    for bar in four_hour:
        decision_time = bar.close_time_utc_ms
        if not decision_start_utc_ms <= decision_time <= decision_end_utc_ms:
            continue
        result = build_candidate(
            symbol=symbol,
            daily_bars=daily,
            four_hour_bars=four_hour,
            training_start_utc_ms=training_start_utc_ms,
            decision_time_utc_ms=decision_time,
            code_commit=code_commit,
            dependency_lock_hash=dependency_lock_hash,
        )
        if isinstance(result, StrategyCandidate):
            candidates.append(result)
        else:
            failures.append(result)
    return CandidateStream(tuple(candidates), tuple(failures))


def _require_contiguous(bars: tuple[Kline, ...], step: int, label: str) -> None:
    if any(
        right.open_time_utc_ms - left.open_time_utc_ms != step for left, right in pairwise(bars)
    ):
        raise CanonicalDataError(f"{label} active segment is not continuous")


def build_actionable_candidate_stream(
    *,
    symbol: str,
    daily_bars: Iterable[Kline],
    four_hour_bars: Iterable[Kline],
    training_start_utc_ms: int,
    decision_start_utc_ms: int,
    decision_end_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> ActionableCandidateStream:
    """Compute indicators once while preserving frozen Candidate bytes for actionable bars."""
    assert_runtime_lock()
    daily_all = tuple(sorted(daily_bars, key=lambda item: item.open_time_utc_ms))
    four_all = tuple(sorted(four_hour_bars, key=lambda item: item.open_time_utc_ms))
    pre_roll = select_exact_pre_roll(
        daily_all,
        four_all,
        training_start_utc_ms=training_start_utc_ms,
    )
    daily = pre_roll.daily + tuple(
        bar
        for bar in daily_all
        if training_start_utc_ms <= bar.open_time_utc_ms
        and bar.close_time_utc_ms <= decision_end_utc_ms
    )
    four_hour = pre_roll.four_hour + tuple(
        bar
        for bar in four_all
        if training_start_utc_ms <= bar.open_time_utc_ms
        and bar.close_time_utc_ms <= decision_end_utc_ms
    )
    _require_contiguous(daily, 86_400_000, "1d")
    _require_contiguous(four_hour, 14_400_000, "4h")
    if any(not bar.is_closed for bar in (*daily, *four_hour)):
        raise CanonicalDataError("UNCLOSED_BAR")
    daily_closes = [bar.close for bar in daily]
    daily_close_times = [bar.close_time_utc_ms for bar in daily]
    ema50 = ema(daily_closes, 50)
    ema200 = ema(daily_closes, 200)
    highs = [bar.high for bar in four_hour]
    lows = [bar.low for bar in four_hour]
    closes = [bar.close for bar in four_hour]
    atr14 = wilder_atr(highs, lows, closes, 14)
    state = VisibleValidationState()
    daily_json = tuple(canonical_dumps(bar) for bar in daily)
    four_hour_json = tuple(canonical_dumps(bar) for bar in four_hour)
    output: list[StrategyCandidate] = []
    trend_evidence: list[TrendEvidence] = []
    counts = {"LONG": 0, "SHORT": 0, "NO_SETUP": 0}
    for index, current in enumerate(four_hour):
        decision_time = current.close_time_utc_ms
        if not decision_start_utc_ms <= decision_time <= decision_end_utc_ms:
            continue
        daily_index = bisect_right(daily_close_times, decision_time) - 1
        if daily_index < 0 or ema50[daily_index] is None or ema200[daily_index] is None:
            raise CanonicalDataError("daily indicator is warming up")
        if atr14[index] is None or index < 20:
            raise CanonicalDataError("four-hour indicator is warming up")
        ema50_value = float64_to_decimal_15sig(ema50[daily_index])
        ema200_value = float64_to_decimal_15sig(ema200[daily_index])
        atr_value = float64_to_decimal_15sig(atr14[index])
        donchian_high, donchian_low = previous_donchian(
            highs,
            lows,
            index=index,
            lookback=20,
        )
        daily_close = daily[daily_index].close
        if daily_close > ema200_value and ema50_value > ema200_value:
            trend = TrendState.BULL
        elif daily_close < ema200_value and ema50_value < ema200_value:
            trend = TrendState.BEAR
        else:
            trend = TrendState.NEUTRAL
        trend_evidence.append(
            TrendEvidence(
                decision_time_utc_ms=decision_time,
                trend_state=trend,
                is_closed=True,
                content_hash=canonical_sha256(
                    {
                        "schema_version": "TREND_EVIDENCE_2D_V1",
                        "symbol": symbol,
                        "decision_time_utc_ms": decision_time,
                        "daily_close": daily_close,
                        "ema50_daily": ema50_value,
                        "ema200_daily": ema200_value,
                        "trend_state": trend.value,
                    }
                ),
                symbol=symbol,
            )
        )
        market = classify_market(
            trend_state=trend,
            current_close=current.close,
            donchian_high=donchian_high,
            donchian_low=donchian_low,
        )
        counts[market.market_view.value] += 1
        if market.market_view not in {MarketView.LONG, MarketView.SHORT}:
            continue
        visible_hash = _visible_hash_from_serialized(
            symbol=symbol,
            decision_time_utc_ms=decision_time,
            training_start_utc_ms=training_start_utc_ms,
            daily_json=daily_json[: daily_index + 1],
            four_hour_json=four_hour_json[: index + 1],
            validation_state=state,
        )
        output.append(
            strategy_candidate(
                symbol=symbol,
                decision_time_utc_ms=decision_time,
                decision_bar_open_time_utc_ms=current.open_time_utc_ms,
                market_view=market.market_view,
                market_reason=market.market_reason,
                decision_close=current.close,
                daily_close=daily_close,
                trend_state=trend,
                ema50_daily=ema50_value,
                ema200_daily=ema200_value,
                atr14_4h=atr_value,
                donchian_high_previous_20=donchian_high,
                donchian_low_previous_20=donchian_low,
                decision_visible_input_hash=visible_hash,
                indicator_config_hash=INDICATOR_CONFIG_HASH,
                strategy_config_hash=STRATEGY_CONFIG_HASH,
                code_commit=code_commit,
                dependency_lock_hash=dependency_lock_hash,
            )
        )
    return ActionableCandidateStream(tuple(output), counts, tuple(trend_evidence))
