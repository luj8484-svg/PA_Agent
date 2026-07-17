from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import require_sha256

SUPPORTED_SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def _price(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a finite positive Decimal")


@dataclass(frozen=True, slots=True)
class MinuteBar:
    symbol: str
    open_time_utc_ms: int
    close_time_utc_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    is_closed: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.symbol not in SUPPORTED_SYMBOLS:
            raise ValueError("unsupported market symbol")
        if (
            type(self.open_time_utc_ms) is not int
            or self.open_time_utc_ms < 0
            or self.open_time_utc_ms % 60_000
            or self.close_time_utc_ms != self.open_time_utc_ms + 59_999
        ):
            raise ValueError("bar must cover one exact UTC minute")
        for name in ("open", "high", "low", "close"):
            _price(getattr(self, name), name)
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC geometry is invalid")
        if type(self.is_closed) is not bool:
            raise ValueError("is_closed must be bool")
        require_sha256(self.content_hash, "bar content_hash")


@dataclass(frozen=True, slots=True)
class MinuteInputSlice:
    minute_open_utc_ms: int
    trade_bars: tuple[MinuteBar, ...]
    mark_bars: tuple[MinuteBar, ...]
    funding_records: tuple[object, ...]
    due_intents: tuple[object, ...]
    funding_expected: bool = False
    index_expected: bool = False
    index_present: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.minute_open_utc_ms) is not int
            or self.minute_open_utc_ms < 0
            or self.minute_open_utc_ms % 60_000
        ):
            raise ValueError("slice must start at a UTC one-minute boundary")
        for bar in self.trade_bars + self.mark_bars:
            if bar.open_time_utc_ms != self.minute_open_utc_ms:
                raise ValueError("bar minute does not match input slice")
        for bars in (self.trade_bars, self.mark_bars):
            symbols = tuple(bar.symbol for bar in bars)
            if symbols != tuple(sorted(set(symbols))):
                raise ValueError("bar symbols must be unique and sorted")


@dataclass(frozen=True, slots=True)
class PathInvalidEvent:
    event_time_utc_ms: int
    reason: str


@dataclass(frozen=True, slots=True)
class ValidatedMinuteInputs:
    minute: MinuteInputSlice
    audit_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationInputs:
    minute_slices: tuple[MinuteInputSlice, ...]
    candidates: tuple[object, ...]
    evidence_hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        opens = tuple(item.minute_open_utc_ms for item in self.minute_slices)
        if opens != tuple(sorted(set(opens))):
            raise ValueError("simulation minute slices must be unique and sorted")
        names = tuple(name for name, _ in self.evidence_hashes)
        if names != tuple(sorted(set(names))):
            raise ValueError("simulation evidence names must be unique and sorted")
        for _, digest in self.evidence_hashes:
            require_sha256(digest, "simulation evidence hash")


def validate_minute_inputs(
    *, has_positions: bool, has_due_event: bool, minute: MinuteInputSlice
) -> ValidatedMinuteInputs | PathInvalidEvent:
    all_bars = minute.trade_bars + minute.mark_bars
    if any(not bar.is_closed for bar in all_bars):
        return PathInvalidEvent(minute.minute_open_utc_ms, "UNCLOSED_BAR")
    audit: list[str] = []
    if not minute.trade_bars:
        if has_positions:
            return PathInvalidEvent(minute.minute_open_utc_ms, "TRADE_GAP_AFFECTS_POSITION")
        if has_due_event:
            return PathInvalidEvent(minute.minute_open_utc_ms, "TRADE_GAP_AFFECTS_EVENT")
        audit.append("TRADE_GAP")
    if not minute.mark_bars:
        if has_positions:
            return PathInvalidEvent(minute.minute_open_utc_ms, "MARK_GAP_AFFECTS_POSITION")
        audit.append("MARK_GAP")
    if minute.funding_expected and has_positions and not minute.funding_records:
        return PathInvalidEvent(minute.minute_open_utc_ms, "FUNDING_GAP_AFFECTS_POSITION")
    if minute.index_expected and not minute.index_present:
        audit.append("INDEX_GAP")
    return ValidatedMinuteInputs(minute, tuple(audit))
