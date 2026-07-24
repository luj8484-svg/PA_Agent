from dataclasses import replace

from pa_agent.research_2d.capacity import (
    capacity_projection,
    capacity_projection_hash,
    select_safe_worker_count,
)
from pa_agent.research_2d.parallel import EvaluationTaskResult


def test_capacity_projection_covers_exact_economic_sequences() -> None:
    result = EvaluationTaskResult(
        key="fixture-0",
        runs=(),
        metrics=({"path_kind": "BASELINE", "net_return": "0"},),
        payload_pickle_bytes=100,
        result_pickle_bytes=200,
        worker_pid=1,
        worker_peak_rss_bytes=300,
    )
    projection = capacity_projection(("candidate-a",), result)
    assert projection["candidates"] == ("candidate-a",)
    assert projection["runs"] == ()
    assert projection["metrics"] == result.metrics
    changed = replace(result, metrics=({"path_kind": "BASELINE", "net_return": "0.1"},))
    assert capacity_projection_hash(("candidate-a",), result) != capacity_projection_hash(
        ("candidate-a",), changed
    )


def test_safe_worker_selection_uses_measured_memory_margin() -> None:
    measurements = {
        "1": {"passed": True, "memory_with_margin_bytes": 20},
        "2": {"passed": True, "memory_with_margin_bytes": 50},
        "6": {"passed": True, "memory_with_margin_bytes": 120},
    }
    assert select_safe_worker_count(measurements, available_memory_bytes=100) == 2
