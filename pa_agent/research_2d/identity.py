from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pa_agent.research_backtest.domain.canonical import canonical_sha256

SPLIT_CANDIDATE_VERSION = "EXPERIMENT_SPLIT_CANDIDATE_V3"
EXPERIMENT_IDENTITY_VERSION = "COMPUTATIONAL_EXPERIMENT_IDENTITY_V1"

EXPERIMENT_DEPENDENCY_FIELDS = (
    "approved_data_bundle_hash",
    "data_approval_manifest_hash",
    "split_manifest_hash",
    "authority_policy_version",
    "strategy_version",
    "two_a_version",
    "two_b_version",
    "planner_config_hash",
    "two_c_version",
    "fee_model_version",
    "slippage_model_version",
    "funding_model_version",
    "contract_approximation_version",
    "maintenance_approximation_version",
    "path_policy_version",
    "code_commit",
    "dependency_lock_hash",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,64}")


def build_split_candidate_v3(v2: Mapping[str, Any]) -> dict[str, Any]:
    """Correct the short split identity without claiming an experiment identity."""
    if v2.get("version") != "EXPERIMENT_SPLIT_CANDIDATE_V2":
        raise ValueError("split candidate source must be EXPERIMENT_SPLIT_CANDIDATE_V2")
    short_id = v2.get("computational_experiment_id")
    if not isinstance(short_id, str) or not short_id:
        raise ValueError("V2 computational_experiment_id must be a nonempty short identity")
    result = dict(v2)
    result.pop("computational_experiment_id")
    result["version"] = SPLIT_CANDIDATE_VERSION
    result["split_candidate_id"] = short_id
    return result


def build_experiment_identity_payload(values: Mapping[str, str]) -> dict[str, str]:
    actual = set(values)
    expected = set(EXPERIMENT_DEPENDENCY_FIELDS)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"experiment dependency fields mismatch: missing={missing}, extra={extra}")
    for name, value in values.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a nonempty string")
        if name.endswith("_hash") and _SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    if _COMMIT_RE.fullmatch(values["code_commit"]) is None:
        raise ValueError("code_commit must be 7-64 lowercase hexadecimal characters")
    return {
        "schema_version": EXPERIMENT_IDENTITY_VERSION,
        **{name: values[name] for name in EXPERIMENT_DEPENDENCY_FIELDS},
    }


def computational_experiment_id(payload: Mapping[str, str]) -> str:
    if payload.get("schema_version") != EXPERIMENT_IDENTITY_VERSION:
        raise ValueError("unsupported computational experiment identity schema")
    expected = {"schema_version", *EXPERIMENT_DEPENDENCY_FIELDS}
    if set(payload) != expected:
        raise ValueError("computational experiment identity payload is not closed")
    return canonical_sha256(payload)
