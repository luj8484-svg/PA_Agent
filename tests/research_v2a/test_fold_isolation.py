from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.runner import Scenario
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_v2a.domain import WALK_FORWARD_FOLDS, StrategyIdentity
from pa_agent.research_v2a.identity import ExperimentIdentity
from pa_agent.research_v2a.walk_forward import WalkForwardTask, run_walk_forward_task
from tests.research_v2a.helpers import make_candidate


def _identity() -> ExperimentIdentity:
    return ExperimentIdentity(
        schema_version="V2A_EXPERIMENT_IDENTITY_V1",
        strategy_identities=(
            StrategyIdentity.V1_BASELINE,
            StrategyIdentity.V2A_Q50,
        ),
        fold_manifest_hashes=("1" * 64,),
        threshold_manifest_hashes=("2" * 64,),
        threshold_calculation_hashes=("3" * 64,),
        dataset_content_hash="4" * 64,
        code_commit="5" * 40,
        dependency_lock_hash="6" * 64,
        candidate_filter_version="BREAKOUT_QUALITY_FILTER_V2A_V1",
        computational_experiment_id="7" * 64,
    )


def test_run_task_uses_independent_fold_bounds_and_filtered_candidates(
    monkeypatch, tmp_path: Path
) -> None:
    fold = WALK_FORWARD_FOLDS[0]
    accepted = make_candidate(
        decision_time_utc_ms=fold.validation_start_utc_ms,
        strength="4",
    )
    rejected = make_candidate(
        decision_time_utc_ms=fold.validation_start_utc_ms + 14_400_000,
        strength="1",
        suffix="f",
    )
    task = WalkForwardTask(
        key="F1:V2A_Q50:NATIVE_PRIMARY:BASE_1X",
        fold=fold,
        strategy_identity=StrategyIdentity.V2A_Q50,
        authority="NATIVE_PRIMARY",
        scenario=Scenario("BASE_1X", Decimal("1"), Decimal("1")),
        initial_capital=Decimal("10000"),
        accepted_candidate_ids=(accepted.candidate_id,),
        accepted_candidate_content_hash=canonical_sha256((accepted,)),
    )
    captured = {}

    monkeypatch.setattr(
        "pa_agent.research_v2a.walk_forward._load_candidates",
        lambda *args, **kwargs: ((accepted, rejected), ("trend",), {}, {}),
    )
    monkeypatch.setattr(
        "pa_agent.research_v2a.walk_forward._market_evidence",
        lambda *args, **kwargs: ("evidence",),
    )
    monkeypatch.setattr(
        "pa_agent.research_v2a.walk_forward.verify_data_approval_manifest",
        lambda path: type("Approval", (), {"manifest_hash": "9" * 64})(),
    )

    def fake_run_scenario(**kwargs):
        captured.update(kwargs)
        return (("run",), [{"path_state": "VALID"}])

    monkeypatch.setattr("pa_agent.research_v2a.walk_forward._run_scenario", fake_run_scenario)

    result = run_walk_forward_task(
        task,
        root=tmp_path,
        experiment_identity=_identity(),
    )

    assert captured["split"].start_utc_ms == fold.validation_start_utc_ms
    assert captured["split"].end_utc_ms == fold.validation_end_utc_ms
    assert captured["candidates"] == (accepted,)
    assert captured["trends"] == ("trend",)
    assert result.runs == ("run",)
    assert result.metrics == ({"path_state": "VALID"},)


def test_every_registry_task_starts_with_independent_10000_usdt() -> None:
    from pa_agent.research_v2a.walk_forward import build_walk_forward_tasks
    from tests.research_v2a.test_registry import BASE, _preflight

    tasks = build_walk_forward_tasks(
        preflight=_preflight((StrategyIdentity.V1_BASELINE, StrategyIdentity.V2A_Q50)),
        folds=WALK_FORWARD_FOLDS,
        baseline_scenario=BASE,
    )

    assert all(task.initial_capital == Decimal("10000") for task in tasks)
    assert not any(
        hasattr(task, name)
        for task in tasks
        for name in ("wallet", "position", "equity", "previous_fold")
    )
