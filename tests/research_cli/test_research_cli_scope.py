import socket
from pathlib import Path

import pa_agent.research_cli as research_cli

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SOURCE_TOKENS = (
    "create_order",
    "API_KEY",
    "SECRET_KEY",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "PyQt",
    "pa_agent.main",
    "pa_agent.gui",
    "pa_agent.app_context",
)


def test_research_cli_source_contains_no_forbidden_capability() -> None:
    source = (ROOT / "pa_agent" / "research_cli.py").read_text(encoding="utf-8")
    assert not {token for token in FORBIDDEN_SOURCE_TOKENS if token in source}


def test_validate_environment_does_not_open_network(monkeypatch, capsys) -> None:
    def blocked(*_args, **_kwargs):
        raise AssertionError("research environment validation attempted network access")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    assert research_cli.main(["validate-environment"]) == 0
    assert "network_access=not_performed" in capsys.readouterr().out


def test_packaging_exposes_separate_research_and_legacy_gui_entries() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'pa-research = "pa_agent.research_cli:main"' in pyproject
    assert 'pa-agent-gui = "pa_agent.main:main"' in pyproject


def test_documentation_forbids_legacy_gui_paths_in_research_automation() -> None:
    guide = (ROOT / "docs" / "research_cli.md").read_text(encoding="utf-8")
    assert "python -m pa_agent.research_cli --help" in guide
    assert "pa-research --help" in guide
    assert "run.py" in guide
    assert "pa-agent-gui" in guide
    assert "must not use legacy GUI entry points" in guide
    assert "--run-gui-tests" in guide
    assert "--run-legacy-e2e" in guide


def test_makefile_exposes_side_effect_free_research_commands() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "research-help:" in makefile
    assert "research-version:" in makefile
    assert "research-validate:" in makefile
