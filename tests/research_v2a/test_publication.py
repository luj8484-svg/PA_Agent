from pathlib import Path

import pytest

from pa_agent.research_2d.parallel import OutputRootLockedError, exclusive_output_lock
from pa_agent.research_v2a.reporting import publish_walk_forward_report


def test_exclusive_output_lock_prevents_concurrent_parent_publication(
    tmp_path: Path,
) -> None:
    with (
        exclusive_output_lock(tmp_path),
        pytest.raises(OutputRootLockedError),
        exclusive_output_lock(tmp_path),
    ):
        pass


def test_failed_publication_leaves_no_partial_official_directory(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "official"

    def fail_replace(source, target):
        raise OSError("simulated publication failure")

    monkeypatch.setattr("pa_agent.research_v2a.reporting.os.replace", fail_replace)
    with pytest.raises(OSError):
        publish_walk_forward_report(
            output_dir=output,
            canonical_economics={"status": "complete"},
            diagnostics={"runtime": "separate"},
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".official.*.tmp"))
