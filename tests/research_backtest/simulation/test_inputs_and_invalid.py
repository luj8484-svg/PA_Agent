from decimal import Decimal

import pytest


def bar(symbol: str = "BTCUSDT", *, closed: bool = True):
    from pa_agent.research_backtest.simulation.inputs import MinuteBar

    return MinuteBar(
        symbol=symbol,
        open_time_utc_ms=60_000,
        close_time_utc_ms=119_999,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        is_closed=closed,
        content_hash="a" * 64,
    )


def test_unclosed_bar_fails_closed() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=False,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (bar(closed=False),), (bar(),), (), ()),
    )
    assert result.reason == "UNCLOSED_BAR"


def test_held_position_trade_gap_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=True,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (), (bar(),), (), ()),
    )
    assert result.reason == "TRADE_GAP_AFFECTS_POSITION"


def test_held_position_mark_gap_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=True,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (bar(),), (), (), ()),
    )
    assert result.reason == "MARK_GAP_AFFECTS_POSITION"


def test_flat_irrelevant_gap_is_only_recorded() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        ValidatedMinuteInputs,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=False,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (), (), (), ()),
    )
    assert isinstance(result, ValidatedMinuteInputs)
    assert result.audit_gaps == ("TRADE_GAP", "MARK_GAP")


def test_due_entry_requires_trade_but_not_mark() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        ValidatedMinuteInputs,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=False,
        has_due_event=True,
        minute=MinuteInputSlice(60_000, (bar(),), (), (), ("intent",)),
    )
    assert isinstance(result, ValidatedMinuteInputs)
    assert result.audit_gaps == ("MARK_GAP",)


def test_due_entry_without_trade_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=False,
        has_due_event=True,
        minute=MinuteInputSlice(60_000, (), (bar(),), (), ("intent",)),
    )
    assert result.reason == "TRADE_GAP_AFFECTS_EVENT"


def test_expected_funding_missing_while_held_is_invalid() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=True,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (bar(),), (bar(),), (), (), funding_expected=True),
    )
    assert result.reason == "FUNDING_GAP_AFFECTS_POSITION"


def test_index_gap_never_invalidates() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        ValidatedMinuteInputs,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=False,
        has_due_event=False,
        minute=MinuteInputSlice(60_000, (bar(),), (bar(),), (), (), index_expected=True),
    )
    assert isinstance(result, ValidatedMinuteInputs)
    assert result.audit_gaps == ("INDEX_GAP",)


def test_misaligned_bar_is_rejected() -> None:
    from pa_agent.research_backtest.simulation.inputs import MinuteBar

    with pytest.raises(ValueError, match="minute"):
        MinuteBar("BTCUSDT", 1, 60_000, *(Decimal("1"),) * 4, True, "a" * 64)


def test_invalid_projection_does_not_fabricate_equity() -> None:
    from pa_agent.research_backtest.simulation.inputs import PathInvalidEvent
    from pa_agent.research_backtest.simulation.output import terminal_invalid_projection

    result = terminal_invalid_projection(PathInvalidEvent(60_000, "MARK_GAP_AFFECTS_POSITION"))
    assert result.path_result.path_state.value == "INVALID"
    assert result.equity_points == ()
    assert result.ledger_entries == ()


def test_missing_held_symbol_bar_fails_in_data_gate() -> None:
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    result = validate_minute_inputs(
        has_positions=True,
        has_due_event=False,
        held_symbols=("ETHUSDT",),
        minute=MinuteInputSlice(60_000, (bar("BTCUSDT"),), (bar("BTCUSDT"),), (), ()),
    )
    assert result.reason == "TRADE_GAP_AFFECTS_POSITION:ETHUSDT"


def test_missing_funding_record_is_checked_per_held_symbol() -> None:
    from pa_agent.research_backtest.simulation.funding import FundingRecord
    from pa_agent.research_backtest.simulation.inputs import (
        MinuteInputSlice,
        validate_minute_inputs,
    )

    record = FundingRecord(
        "btc-funding",
        "BTCUSDT",
        60_000,
        Decimal("0.0001"),
        Decimal("100"),
        "b" * 64,
    )
    result = validate_minute_inputs(
        has_positions=True,
        has_due_event=False,
        held_symbols=("BTCUSDT", "ETHUSDT"),
        minute=MinuteInputSlice(
            60_000,
            (bar("BTCUSDT"), bar("ETHUSDT")),
            (bar("BTCUSDT"), bar("ETHUSDT")),
            (record,),
            (),
            funding_expected=True,
            funding_expected_symbols=("BTCUSDT", "ETHUSDT"),
        ),
    )
    assert result.reason == "FUNDING_GAP_AFFECTS_POSITION:ETHUSDT"
