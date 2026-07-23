import json
from pathlib import Path

from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_v2a.reporting import publish_walk_forward_report


def test_canonical_economics_excludes_runtime_diagnostics(tmp_path: Path) -> None:
    economics = {"selection": "V2A_Q50", "folds": [1, 2, 3, 4]}
    first = publish_walk_forward_report(
        output_dir=tmp_path / "first",
        canonical_economics=economics,
        diagnostics={"generated_at": "now", "pid": 1, "duration": 3},
    )
    second = publish_walk_forward_report(
        output_dir=tmp_path / "second",
        canonical_economics=economics,
        diagnostics={"generated_at": "later", "pid": 999, "duration": 8},
    )

    assert first.canonical_hash == second.canonical_hash == canonical_sha256(economics)
    assert json.loads((first.output_dir / "canonical_report.json").read_text()) == economics
    assert json.loads((first.output_dir / "diagnostics.json").read_text())["pid"] == 1


def test_publication_is_atomic_and_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "published"
    publish_walk_forward_report(
        output_dir=output,
        canonical_economics={"status": "complete"},
        diagnostics={},
    )
    assert output.is_dir()
    assert not list(tmp_path.glob(".published.*.tmp"))

    try:
        publish_walk_forward_report(
            output_dir=output,
            canonical_economics={"status": "replacement"},
            diagnostics={},
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("published output must not be overwritten")
