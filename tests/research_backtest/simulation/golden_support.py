from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from types import SimpleNamespace

from pa_agent.research_backtest.domain.canonical import canonical_sha256

_GOLDENS = Path(__file__).parent / "fixtures" / "timeline_full_goldens_v1.json"


def _fixture_value(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _fixture_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, SimpleNamespace):
        return {name: _fixture_value(item) for name, item in vars(value).items()}
    if isinstance(value, dict):
        return {name: _fixture_value(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_fixture_value(item) for item in value)
    return value


def assert_full_golden(
    scenario_id: str,
    *,
    input_fixture: object,
    event_sequence: object,
    ledger: object,
    fill_trade: object,
    equity: object,
    path_result: object,
) -> None:
    payload = json.loads(_GOLDENS.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["scenario_id"] == scenario_id)
    actual = {
        "input_fixture_hash": canonical_sha256(_fixture_value(input_fixture)),
        "event_sequence_hash": canonical_sha256(_fixture_value(event_sequence)),
        "ledger_hash": canonical_sha256(_fixture_value(ledger)),
        "fill_trade_hash": canonical_sha256(_fixture_value(fill_trade)),
        "equity_hash": canonical_sha256(_fixture_value(equity)),
        "path_result_hash": canonical_sha256(_fixture_value(path_result)),
    }
    expected = {name: case[name] for name in actual}
    assert actual == expected, {"actual": actual, "expected": expected}
