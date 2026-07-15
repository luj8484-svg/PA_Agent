from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps
from pa_agent.research_backtest.testing.registry import (
    FrozenDocumentPaths,
    ImplementedTest,
    RegistryValidationError,
    load_documented_master_registry,
    validate_registry,
)
from pa_agent.research_backtest.testing.scope import scan_forbidden_capabilities


def registered(test_id: str, *requirement_ids: str):
    def decorate(function):
        marked = pytest.mark.requirement_ids(*requirement_ids)(function)
        return pytest.mark.test_id(test_id)(marked)

    return decorate


@dataclass(frozen=True)
class ExampleObject:
    schema_version: str
    object_id: str
    content_hash: str
    amount: Decimal


@registered("UT-ID-001", "2B-ID-001")
def test_formal_identity_is_content_addressed_and_self_verifying() -> None:
    payload = {"schema_version": "EXAMPLE_V1", "amount": Decimal("1.2300")}
    object_id, digest = formal_identity("example_", payload)
    value = ExampleObject("EXAMPLE_V1", object_id, digest, Decimal("1.23"))
    verify_formal_identity(
        value,
        id_field="object_id",
        hash_field="content_hash",
        prefix="example_",
    )


@registered("UT-ID-002", "2B-ID-002")
def test_canonical_rejects_non_string_map_keys_and_binary_float() -> None:
    assert canonical_dumps({"b": Decimal("0.00"), "a": Decimal("1.2300")}) == (
        '{"a":"1.23","b":"0"}'
    )
    with pytest.raises(TypeError):
        canonical_dumps({1: "forbidden"})
    with pytest.raises(TypeError):
        canonical_dumps({"value": 1.0})


def _write_sources(root: Path, values: tuple[str, ...]) -> FrozenDocumentPaths:
    paths = []
    for index, value in enumerate(values):
        path = root / f"source-{index}.md"
        path.write_text(value, encoding="utf-8")
        paths.append(path)
    return FrozenDocumentPaths(*paths)


@registered("UT-ID-008", "2B-ID-008")
def test_master_registry_is_five_source_union_and_excludes_fixture_ids(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        (
            "| 2B-ID-008 | x | UT-ID-008 | PT-MASTER-REGISTRY-UNION | GF-ONE |",
            "2B-ID-008 UT-ILLEGAL-01-01",
            "2B-ID-008 UT-TB-01-01",
            "2B-ID-008 UT-GF-01-01 GF-TWO",
            "2B-ID-008 UT-RT-53-01",
        ),
    )
    registry = load_documented_master_registry(paths)
    assert {item.test_id for item in registry} == {
        "UT-ID-008",
        "PT-MASTER-REGISTRY-UNION",
        "UT-ILLEGAL-01-01",
        "UT-TB-01-01",
        "UT-GF-01-01",
        "UT-RT-53-01",
    }
    assert next(item for item in registry if item.test_id == "UT-ID-008").requirement_ids == (
        "2B-ID-008",
    )


@registered("UT-SCOPE-006", "2B-SCOPE-006")
def test_registry_validator_fails_empty_missing_or_orphan_implementations(tmp_path: Path) -> None:
    documented = load_documented_master_registry(
        _write_sources(tmp_path, ("| 2B-ID-008 | x | UT-ID-008 |", "", "", "", ""))
    )
    with pytest.raises(RegistryValidationError, match="empty implemented"):
        validate_registry(documented, ())
    with pytest.raises(RegistryValidationError, match="missing"):
        validate_registry(documented, (ImplementedTest("UT-OTHER-001", ("2B-ID-008",)),))


@registered("PT-MASTER-REGISTRY-BIJECTION", "2B-SCOPE-006")
def test_registry_validator_rejects_duplicate_test_identity(tmp_path: Path) -> None:
    documented = load_documented_master_registry(
        _write_sources(
            tmp_path,
            ("| 2B-SCOPE-006 | x | PT-MASTER-REGISTRY-BIJECTION |", "", "", "", ""),
        )
    )
    implemented = ImplementedTest("PT-MASTER-REGISTRY-BIJECTION", ("2B-SCOPE-006",))
    with pytest.raises(RegistryValidationError, match="duplicate"):
        validate_registry(documented, (implemented, implemented))


@registered("UT-ID-006", "2B-ID-006")
def test_registry_rejects_empty_requirement_binding() -> None:
    with pytest.raises(ValueError, match="requirement"):
        ImplementedTest("UT-ID-006", ())


@registered("UT-ID-007", "2B-ID-007")
def test_registry_rejects_unknown_requirement(tmp_path: Path) -> None:
    documented = load_documented_master_registry(
        _write_sources(tmp_path, ("| 2B-ID-007 | x | UT-ID-007 |", "", "", "", ""))
    )
    with pytest.raises(RegistryValidationError, match="unknown requirement"):
        validate_registry(documented, (ImplementedTest("UT-ID-007", ("2B-NOPE-001",)),))


@pytest.mark.parametrize(
    ("test_id", "requirement_id", "source", "expected_token"),
    (
        pytest.param(
            "UT-SCOPE-001",
            "2B-SCOPE-001",
            "import requests\n",
            "requests",
            marks=(
                pytest.mark.test_id("UT-SCOPE-001"),
                pytest.mark.requirement_ids("2B-SCOPE-001"),
            ),
        ),
        pytest.param(
            "UT-SCOPE-002",
            "2B-SCOPE-002",
            "__import__('socket')\n",
            "__import__",
            marks=(
                pytest.mark.test_id("UT-SCOPE-002"),
                pytest.mark.requirement_ids("2B-SCOPE-002"),
            ),
        ),
        pytest.param(
            "UT-SCOPE-003",
            "2B-SCOPE-003",
            "from pa_agent.research_backtest.bad_dependency import value\n",
            "urllib.request",
            marks=(
                pytest.mark.test_id("UT-SCOPE-003"),
                pytest.mark.requirement_ids("2B-SCOPE-003"),
            ),
        ),
        pytest.param(
            "UT-SCOPE-004",
            "2B-SCOPE-004",
            "def mutate_account(): pass\n",
            "mutate_account",
            marks=(
                pytest.mark.test_id("UT-SCOPE-004"),
                pytest.mark.requirement_ids("2B-SCOPE-004"),
            ),
        ),
        pytest.param(
            "UT-SCOPE-005",
            "2B-SCOPE-005",
            "from pathlib import Path\nPath('x').read_text()\n",
            "read_text",
            marks=(
                pytest.mark.test_id("UT-SCOPE-005"),
                pytest.mark.requirement_ids("2B-SCOPE-005"),
            ),
        ),
    ),
)
def test_scope_scanner_detects_direct_dynamic_transitive_mutation_and_io(
    tmp_path: Path,
    test_id: str,
    requirement_id: str,
    source: str,
    expected_token: str,
) -> None:
    assert test_id.startswith("UT-SCOPE-") and requirement_id.startswith("2B-SCOPE-")
    package = tmp_path / "package"
    package.mkdir()
    entry = package / "entry.py"
    entry.write_text(source, encoding="utf-8")
    if "bad_dependency" in source:
        (package / "bad_dependency.py").write_text("import urllib.request\n", encoding="utf-8")
    violations = scan_forbidden_capabilities((entry,), package_root=package)
    assert any(expected_token in violation.detail for violation in violations)


@registered("UT-TIME-007", "2B-TIME-007")
def test_scope_scanner_rejects_wall_clock(tmp_path: Path) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text("from datetime import datetime\nvalue = datetime.now()\n", encoding="utf-8")
    violations = scan_forbidden_capabilities((entry,), package_root=tmp_path)
    assert any("datetime.now" in violation.detail for violation in violations)
