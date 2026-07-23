from pathlib import Path

from pa_agent import research_cli


def test_v2a_preflight_cli_is_candidate_only(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return tmp_path / "preflight"

    monkeypatch.setattr(research_cli, "_run_v2a_preflight_command", fake)
    assert (
        research_cli.main(
            [
                "v2a-preflight",
                "--data-root",
                str(tmp_path / "data"),
                "--output-root",
                str(tmp_path / "out"),
                "--code-commit",
                "a" * 40,
            ]
        )
        == 0
    )
    assert captured["root"] == tmp_path / "data"
    assert captured["output_root"] == tmp_path / "out"


def test_v2a_walk_forward_cli_keeps_no_progress_none(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return tmp_path / "result"

    monkeypatch.setattr(research_cli, "_run_v2a_walk_forward_command", fake)
    assert (
        research_cli.main(
            [
                "v2a-walk-forward",
                "--data-root",
                str(tmp_path / "data"),
                "--output-root",
                str(tmp_path / "out"),
                "--code-commit",
                "b" * 40,
                "--max-workers",
                "6",
                "--hard-timeout-seconds",
                "21600",
            ]
        )
        == 0
    )
    assert captured["max_workers"] == 6
    assert captured["hard_timeout_seconds"] == 21_600
    assert captured["no_progress_timeout_seconds"] is None


def test_v2a_cli_source_has_no_key_gui_network_or_order_dependency() -> None:
    source = Path(research_cli.__file__).read_text(encoding="utf-8")
    assert "PyQt" not in source
    assert "requests" not in source
    assert "create_order" not in source
    assert "API_KEY" not in source
