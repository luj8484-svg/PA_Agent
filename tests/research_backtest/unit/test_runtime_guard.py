import inspect
import platform

import pytest


def test_deterministic_research_runtime_is_exact_cpython_31213() -> None:
    from pa_agent.research_backtest.runtime import (
        DETERMINISTIC_RESEARCH_RUNTIME_VERSION,
        assert_deterministic_research_runtime,
        runtime_status,
    )

    assert DETERMINISTIC_RESEARCH_RUNTIME_VERSION == "DETERMINISTIC_RESEARCH_RUNTIME_V1"
    status = runtime_status()
    assert status.implementation == "CPython"
    assert status.version == "3.12.13"
    assert status.status == "PASS"
    assert_deterministic_research_runtime()


@pytest.mark.parametrize(
    ("implementation", "version"),
    (("CPython", "3.12.12"), ("CPython", "3.13.0"), ("PyPy", "3.12.13")),
)
def test_non_frozen_runtime_fails_closed(monkeypatch, implementation, version) -> None:
    from pa_agent.research_backtest.runtime import assert_deterministic_research_runtime

    monkeypatch.setattr(platform, "python_implementation", lambda: implementation)
    monkeypatch.setattr(platform, "python_version", lambda: version)
    with pytest.raises(
        RuntimeError,
        match=r"DETERMINISTIC_RESEARCH_RUNTIME_V1 requires CPython 3\.12\.13",
    ):
        assert_deterministic_research_runtime()


def test_legacy_runtime_lock_delegates_to_formal_guard(monkeypatch) -> None:
    from pa_agent.research_backtest.versions import assert_runtime_lock

    monkeypatch.setattr(platform, "python_version", lambda: "3.12.9")
    with pytest.raises(RuntimeError, match="DETERMINISTIC_RESEARCH_RUNTIME_V1"):
        assert_runtime_lock()


def test_candidate_plan_and_simulation_guard_before_partial_work(monkeypatch) -> None:
    from pa_agent.research_backtest.planning.factory import build_entry_execution_plan
    from pa_agent.research_backtest.simulation.engine import run_simulation
    from pa_agent.research_backtest.strategy.candidate_factory import build_candidate

    monkeypatch.setattr(platform, "python_version", lambda: "3.12.9")
    candidate_kwargs = {
        name: None
        for name, parameter in inspect.signature(build_candidate).parameters.items()
        if parameter.default is inspect.Parameter.empty
    }
    for call in (
        lambda: build_candidate(**candidate_kwargs),
        lambda: build_entry_execution_plan(None),
        lambda: run_simulation(None, None, None),
    ):
        with pytest.raises(RuntimeError, match="DETERMINISTIC_RESEARCH_RUNTIME_V1"):
            call()
