from decimal import Decimal

from pa_agent.research_2d.runner import canonical_report_value
from pa_agent.research_backtest.domain.canonical import canonical_dumps


def test_report_boundary_quantizes_all_binary_floats_before_canonical_json() -> None:
    value = {"metric": 0.12345678901234567, "nested": [1.5, {"count": 2}]}
    converted = canonical_report_value(value)
    assert converted == {
        "metric": Decimal("0.123456789012346"),
        "nested": (Decimal("1.5"), {"count": 2}),
    }
    assert canonical_dumps(converted)
