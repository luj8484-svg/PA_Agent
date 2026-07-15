from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from pa_agent.research_backtest.domain.canonical import canonical_sha256

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,64}")


def require_nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def require_commit(value: object) -> str:
    if not isinstance(value, str) or COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError("code_commit must be a lowercase hexadecimal commit identity")
    return value


def require_utc_ms(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be nonnegative integer UTC milliseconds")
    return value


def formal_identity(prefix: str, payload: object) -> tuple[str, str]:
    require_nonempty_string(prefix, "identity prefix")
    digest = canonical_sha256(payload)
    return f"{prefix}{digest[:24]}", digest


def identity_payload(
    value: object,
    *,
    id_field: str,
    hash_field: str,
) -> dict[str, Any]:
    if not is_dataclass(value):
        raise TypeError("formal identity verification requires a dataclass")
    payload = asdict(value)
    try:
        payload.pop(id_field)
        payload.pop(hash_field)
    except KeyError as exc:
        raise ValueError("formal object is missing its identity fields") from exc
    return payload


def verify_formal_identity(
    value: object,
    *,
    id_field: str,
    hash_field: str,
    prefix: str,
) -> None:
    object_id = getattr(value, id_field, None)
    content_hash = getattr(value, hash_field, None)
    require_sha256(content_hash, hash_field)
    expected_id, expected_hash = formal_identity(
        prefix,
        identity_payload(value, id_field=id_field, hash_field=hash_field),
    )
    if content_hash != expected_hash:
        raise ValueError(f"{hash_field} does not match Canonical content")
    if object_id != expected_id:
        raise ValueError(f"{id_field} does not match Canonical content")
