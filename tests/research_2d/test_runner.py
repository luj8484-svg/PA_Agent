import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pa_agent.research_2d.runner import (
    Split,
    _reconcile_authorities,
    _required_evidence_targets,
    canonical_report_value,
    experiment_temporary_directory,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps


def test_report_boundary_quantizes_all_binary_floats_before_canonical_json() -> None:
    value = {"metric": 0.12345678901234567, "nested": [1.5, {"count": 2}]}
    converted = canonical_report_value(value)
    assert converted == {
        "metric": Decimal("0.123456789012346"),
        "nested": (Decimal("1.5"), {"count": 2}),
    }
    assert canonical_dumps(converted)


def test_required_evidence_targets_include_delayed_trend_exit_minute() -> None:
    split = Split("OOS", 0, 7 * 24 * 60 * 60 * 1000 - 1)
    candidate = SimpleNamespace(symbol="ETHUSDT", decision_time_utc_ms=14_399_999)
    trend = SimpleNamespace(symbol="ETHUSDT", decision_time_utc_ms=20_459_999)

    required = _required_evidence_targets((candidate,), (trend,), split)

    assert ("ETHUSDT", 20_520_000) in required
    entry_target = candidate.decision_time_utc_ms + 1 + 60_000
    assert ("ETHUSDT", entry_target + 48 * 60 * 60 * 1000 + 120_000) in required


def test_authority_reconciliation_ignores_identity_only_differences() -> None:
    def run(prefix: str):
        fill = SimpleNamespace(
            fill_id=f"{prefix}-fill",
            plan_id=f"{prefix}-plan",
            symbol="BTCUSDT",
            side=SimpleNamespace(value="LONG"),
            action=SimpleNamespace(value="ENTRY"),
            event_time_utc_ms=60_000,
            quantity=Decimal("0.1"),
            fill_price=Decimal("100"),
            fee=Decimal("0.01"),
            selected_exit_reason=None,
            matched_exit_reasons=(),
        )
        trade = SimpleNamespace(
            origin_candidate_id=f"{prefix}-candidate",
            symbol="BTCUSDT",
            side=SimpleNamespace(value="LONG"),
            entry_time_utc_ms=60_000,
            exit_time_utc_ms=120_000,
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            quantity=Decimal("0.1"),
            entry_fee=Decimal("0.01"),
            exit_fee=Decimal("0.01"),
            funding=Decimal("0"),
            gross_pnl=Decimal("0.1"),
            net_pnl=Decimal("0.08"),
            exit_reason="PROTECTIVE",
        )
        return SimpleNamespace(
            path_kind=SimpleNamespace(value="BASELINE"), fills=(fill,), trades=(trade,)
        )

    result = _reconcile_authorities(
        (run("native"),),
        (run("aggregated"),),
        ({"path_kind": "BASELINE", "net_return": "0.01", "maximum_drawdown": "0.02"},),
        ({"path_kind": "BASELINE", "net_return": "0.01", "maximum_drawdown": "0.02"},),
    )

    assert result["BASELINE"]["economic_outputs_match"] is True
    assert result["BASELINE"]["affected_native_trade_ids"] == ()
    assert result["BASELINE"]["affected_aggregated_trade_ids"] == ()


def test_experiment_temporary_directory_cleans_on_failure(tmp_path: Path) -> None:
    experiment_id = "a" * 64
    try:
        with experiment_temporary_directory(tmp_path, experiment_id) as temporary:
            (temporary / "partial.json").write_text("partial", encoding="utf-8")
            raise RuntimeError("worker failed")
    except RuntimeError:
        pass
    assert not (tmp_path / f".{experiment_id}.tmp").exists()
    assert not (tmp_path / experiment_id).exists()


def test_cli_exposes_parallel_safety_controls() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_2d_baseline_evaluation.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--max-workers {1,2,6}" in completed.stdout
    assert "--hard-timeout-seconds" in completed.stdout
    assert "--no-progress-timeout-seconds" in completed.stdout
