from decimal import Decimal

import pytest

from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.indicators.numeric import float64_to_decimal_15sig
from pa_agent.research_backtest.versions import (
    INDICATOR_CONFIG_VERSION,
    STRATEGY_CANDIDATE_SCHEMA_VERSION,
    STRATEGY_VERSION,
    VALIDATION_FAILURE_SCHEMA_VERSION,
    assert_runtime_lock,
)


def test_formal_versions_and_runtime_are_frozen():
    assert STRATEGY_VERSION == "BTC_ETH_PA_STRATEGY_V1_1"
    assert STRATEGY_CANDIDATE_SCHEMA_VERSION == "STRATEGY_CANDIDATE_SCHEMA_V1"
    assert VALIDATION_FAILURE_SCHEMA_VERSION == "VALIDATION_FAILURE_SCHEMA_V1"
    assert INDICATOR_CONFIG_VERSION == "INDICATOR_CONFIG_V1"
    assert_runtime_lock()


def test_canonical_json_orders_keys_and_normalizes_decimals():
    value = {"z": Decimal("1.2300"), "a": Decimal("-0")}

    assert canonical_dumps(value) == '{"a":"0","z":"1.23"}'
    assert len(canonical_sha256(value)) == 64


def test_canonical_json_rejects_binary_float():
    with pytest.raises(TypeError, match="Binary floats"):
        canonical_dumps({"value": 1.0})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, Decimal("0")),
        (-0.0, Decimal("0")),
        (1.234567890123456, Decimal("1.23456789012346")),
        (5e-324, Decimal("4.94065645841247E-324")),
        (1.7976931348623157e308, Decimal("1.79769313486232E+308")),
    ],
)
def test_float64_to_decimal_uses_fifteen_significant_digits(value, expected):
    assert float64_to_decimal_15sig(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_float64_to_decimal_rejects_non_finite_values(value):
    with pytest.raises(ValueError, match="finite"):
        float64_to_decimal_15sig(value)
