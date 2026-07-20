from __future__ import annotations

import re

import pytest

from pa_agent.research_2d.identity import (
    EXPERIMENT_DEPENDENCY_FIELDS,
    build_experiment_identity_payload,
    build_split_candidate_v3,
    computational_experiment_id,
)

V2 = {
    "version": "EXPERIMENT_SPLIT_CANDIDATE_V2",
    "computational_experiment_id": "exp_31162c08c4245b671c8b8b25",
    "authority_policy_version": "BINANCE_OFFICIAL_SOURCE_AUTHORITY_V1",
    "training_start_utc": "2020-10-01T00:00:00Z",
    "training_end_utc": "2023-09-30T23:59:59.999000Z",
    "validation_start_utc": "2023-10-01T00:00:00Z",
    "validation_end_utc": "2024-09-30T23:59:59.999000Z",
    "oos_start_utc": "2024-10-01T00:00:00Z",
    "oos_end_utc": "2026-03-31T23:59:59.999000Z",
    "pre_roll_content_hash": "1" * 64,
}


def _dependencies() -> dict[str, str]:
    values: dict[str, str] = {}
    for index, field in enumerate(EXPERIMENT_DEPENDENCY_FIELDS, start=1):
        if field.endswith("_hash"):
            values[field] = f"{index:064x}"[-64:]
        elif field == "code_commit":
            values[field] = "a" * 40
        else:
            values[field] = f"{field.upper()}_V1"
    return values


def test_v3_renames_short_identity_without_claiming_full_experiment_id() -> None:
    value = build_split_candidate_v3(V2)

    assert value["version"] == "EXPERIMENT_SPLIT_CANDIDATE_V3"
    assert value["split_candidate_id"] == V2["computational_experiment_id"]
    assert "computational_experiment_id" not in value
    assert value["training_start_utc"] == V2["training_start_utc"]


def test_v3_rejects_wrong_source_version() -> None:
    with pytest.raises(ValueError, match="V2"):
        build_split_candidate_v3(V2 | {"version": "EXPERIMENT_SPLIT_CANDIDATE_V1"})


def test_experiment_id_is_canonical_sha256_and_deterministic() -> None:
    payload = build_experiment_identity_payload(_dependencies())

    first = computational_experiment_id(payload)
    second = computational_experiment_id(dict(reversed(tuple(payload.items()))))

    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert not first.startswith("exp_")


@pytest.mark.parametrize("field", EXPERIMENT_DEPENDENCY_FIELDS)
def test_experiment_id_changes_for_every_dependency(field: str) -> None:
    original = _dependencies()
    changed = dict(original)
    if field.endswith("_hash"):
        changed[field] = "f" * 64 if original[field] != "f" * 64 else "e" * 64
    elif field == "code_commit":
        changed[field] = "b" * 40
    else:
        changed[field] = original[field] + "_CHANGED"

    assert computational_experiment_id(
        build_experiment_identity_payload(original)
    ) != computational_experiment_id(build_experiment_identity_payload(changed))


def test_experiment_identity_rejects_missing_or_extra_dependencies() -> None:
    values = _dependencies()
    values.pop("fee_model_version")
    with pytest.raises(ValueError, match="dependency fields"):
        build_experiment_identity_payload(values)

    with pytest.raises(ValueError, match="dependency fields"):
        build_experiment_identity_payload(_dependencies() | {"download_time": "forbidden"})


def test_experiment_identity_rejects_non_sha_hashes_and_prefixed_ids() -> None:
    with pytest.raises(ValueError, match="approved_data_bundle_hash"):
        build_experiment_identity_payload(
            _dependencies() | {"approved_data_bundle_hash": "not-a-sha256"}
        )
    with pytest.raises(ValueError, match="data_approval_manifest_hash"):
        build_experiment_identity_payload(
            _dependencies() | {"data_approval_manifest_hash": "exp_" + "a" * 64}
        )
