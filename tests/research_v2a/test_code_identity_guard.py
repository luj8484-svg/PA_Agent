from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pa_agent.research_v2a.identity import (
    EXPERIMENT_CODE_IDENTITY_INVALID,
    verify_experiment_code_identity,
)
from pa_agent.research_v2a.walk_forward import (
    run_v2a_candidate_preflight,
    run_v2a_walk_forward,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_code_identity_requires_exact_clean_head_and_approved_ancestor(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "research@example.invalid")
    _git(tmp_path, "config", "user.name", "Research Test")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "baseline")
    baseline = _git(tmp_path, "rev-parse", "HEAD")

    assert (
        verify_experiment_code_identity(
            repository_root=tmp_path,
            code_commit=baseline,
            approved_economic_baseline=baseline,
        )
        == baseline
    )

    with pytest.raises(ValueError, match=EXPERIMENT_CODE_IDENTITY_INVALID):
        verify_experiment_code_identity(
            repository_root=tmp_path,
            code_commit="f" * 40,
            approved_economic_baseline=baseline,
        )

    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match=EXPERIMENT_CODE_IDENTITY_INVALID):
        verify_experiment_code_identity(
            repository_root=tmp_path,
            code_commit=baseline,
            approved_economic_baseline=baseline,
        )


def test_code_identity_rejects_non_full_sha(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=EXPERIMENT_CODE_IDENTITY_INVALID):
        verify_experiment_code_identity(
            repository_root=tmp_path,
            code_commit="abc1234",
            approved_economic_baseline="0" * 40,
        )


def test_formal_entrypoints_fail_before_data_access_for_untrusted_commit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=EXPERIMENT_CODE_IDENTITY_INVALID):
        run_v2a_candidate_preflight(
            root=tmp_path / "missing-data",
            output_root=tmp_path / "preflight",
            code_commit="f" * 40,
        )
    with pytest.raises(ValueError, match=EXPERIMENT_CODE_IDENTITY_INVALID):
        run_v2a_walk_forward(
            root=tmp_path / "missing-data",
            output_root=tmp_path / "walk-forward",
            code_commit="f" * 40,
            max_workers=2,
        )
