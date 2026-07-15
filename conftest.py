"""Repository-wide pytest collection safety boundaries.

Legacy GUI modules are excluded before import unless a caller explicitly opts in.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

GUI_TEST_FILES = frozenset(
    {
        "tests/integration/test_next_bar_prediction.py",
        "tests/integration/test_switch_mid_analysis.py",
        "tests/property/test_next_bar_prediction_perf.py",
        "tests/unit/test_chart_decision_overlay.py",
        "tests/unit/test_chart_fit_view.py",
        "tests/unit/test_chart_skip_redraw.py",
        "tests/unit/test_chart_widget_no_lines_when_not_trading.py",
        "tests/unit/test_debug_widget_masks_key.py",
        "tests/unit/test_decision_panel.py",
        "tests/unit/test_order_opportunity.py",
        "tests/unit/test_overlay_lines.py",
        "tests/unit/test_support_resistance_chart.py",
        "tests/unit/test_token_indicator_thresholds.py",
        "tests/unit/test_validation_retry.py",
    }
)
LEGACY_E2E_FILES = frozenset(
    {
        "tests/e2e/test_smoke_free_chat.py",
        "tests/e2e/test_smoke_happy_path.py",
        "tests/e2e/test_smoke_no_order.py",
        "tests/e2e/test_smoke_switch_mid_flight.py",
    }
)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-gui-tests",
        action="store_true",
        default=False,
        help="collect legacy PyQt/GUI tests (explicit opt-in)",
    )
    parser.addoption(
        "--run-legacy-e2e",
        action="store_true",
        default=False,
        help="collect legacy GUI end-to-end tests (explicit opt-in)",
    )


def _repository_path(collection_path: Path) -> str | None:
    try:
        return collection_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


def pytest_ignore_collect(collection_path: Path, config):
    relative = _repository_path(collection_path)
    if relative in LEGACY_E2E_FILES:
        return not config.getoption("--run-legacy-e2e")
    if relative in GUI_TEST_FILES:
        return not config.getoption("--run-gui-tests")
    return None


def pytest_sessionstart(session) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    if not session.config.getoption("--run-gui-tests"):
        reporter.write_line(
            f"research isolation: GUI files disabled before collection: {len(GUI_TEST_FILES)}"
        )
    if not session.config.getoption("--run-legacy-e2e"):
        reporter.write_line(
            "research isolation: legacy e2e files disabled before collection: "
            f"{len(LEGACY_E2E_FILES)}"
        )
