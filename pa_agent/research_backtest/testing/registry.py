from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TEST_ID_PATTERN = re.compile(r"(?<![A-Z0-9-])((?:UT|PT)-[A-Z0-9]+(?:-[A-Z0-9]+)*)")
REQUIREMENT_ID_PATTERN = re.compile(r"2B-[A-Z]+-[0-9]{3}")


class RegistryValidationError(ValueError):
    """The documented and implemented 2B test registries are not bijective."""


@dataclass(frozen=True, slots=True)
class FrozenDocumentPaths:
    acceptance_matrix: Path
    illegal_state_matrix: Path
    time_boundary_matrix: Path
    golden_fixture_plan: Path
    red_team_matrix: Path

    def ordered(self) -> tuple[Path, ...]:
        return (
            self.acceptance_matrix,
            self.illegal_state_matrix,
            self.time_boundary_matrix,
            self.golden_fixture_plan,
            self.red_team_matrix,
        )


@dataclass(frozen=True, slots=True)
class RegisteredTest:
    test_id: str
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if TEST_ID_PATTERN.fullmatch(self.test_id) is None:
            raise ValueError("invalid test ID")
        if not self.requirement_ids:
            raise ValueError("registered test requires at least one requirement")
        if self.requirement_ids != tuple(sorted(set(self.requirement_ids))):
            raise ValueError("requirement IDs must be unique and sorted")
        if any(REQUIREMENT_ID_PATTERN.fullmatch(value) is None for value in self.requirement_ids):
            raise ValueError("invalid requirement ID")


@dataclass(frozen=True, slots=True)
class ImplementedTest(RegisteredTest):
    pass


@dataclass(frozen=True, slots=True)
class RegistryReport:
    documented_count: int
    implemented_count: int
    requirement_count: int


def load_documented_master_registry(paths: FrozenDocumentPaths) -> tuple[RegisteredTest, ...]:
    bindings: dict[str, set[str]] = {}
    for path in paths.ordered():
        for line in path.read_text(encoding="utf-8").splitlines():
            test_ids = TEST_ID_PATTERN.findall(line)
            if not test_ids:
                continue
            requirement_ids = set(REQUIREMENT_ID_PATTERN.findall(line))
            for test_id in test_ids:
                bindings.setdefault(test_id, set()).update(requirement_ids)
    missing_bindings = sorted(test_id for test_id, values in bindings.items() if not values)
    if missing_bindings:
        raise RegistryValidationError(
            "documented tests have no Requirement binding: " + ", ".join(missing_bindings)
        )
    return tuple(
        RegisteredTest(test_id, tuple(sorted(requirement_ids)))
        for test_id, requirement_ids in sorted(bindings.items())
    )


def validate_registry(
    documented: tuple[RegisteredTest, ...],
    implemented: tuple[ImplementedTest, ...],
) -> RegistryReport:
    if not documented:
        raise RegistryValidationError("empty documented master test registry")
    if not implemented:
        raise RegistryValidationError("empty implemented test registry")
    implemented_ids = [item.test_id for item in implemented]
    duplicates = sorted({value for value in implemented_ids if implemented_ids.count(value) > 1})
    if duplicates:
        raise RegistryValidationError("duplicate implemented test IDs: " + ", ".join(duplicates))

    documented_by_id = {item.test_id: item for item in documented}
    implemented_by_id = {item.test_id: item for item in implemented}
    missing = sorted(set(documented_by_id) - set(implemented_by_id))
    orphan = sorted(set(implemented_by_id) - set(documented_by_id))
    known_requirements = {
        requirement_id for item in documented for requirement_id in item.requirement_ids
    }
    unknown_requirements = sorted(
        {
            requirement_id
            for item in implemented
            for requirement_id in item.requirement_ids
            if requirement_id not in known_requirements
        }
    )
    failures = []
    if missing:
        failures.append("missing documented test IDs: " + ", ".join(missing))
    if orphan:
        failures.append("orphan implemented test IDs: " + ", ".join(orphan))
    if unknown_requirements:
        failures.append("unknown requirement IDs: " + ", ".join(unknown_requirements))
    if failures:
        raise RegistryValidationError("; ".join(failures))
    return RegistryReport(len(documented), len(implemented), len(known_requirements))


def default_document_paths(repository_root: Path) -> FrozenDocumentPaths:
    reviews = repository_root / "docs" / "superpowers" / "reviews"
    return FrozenDocumentPaths(
        reviews / "second-batch-2b-acceptance-matrix.md",
        reviews / "second-batch-2b-illegal-state-matrix.md",
        reviews / "second-batch-2b-time-boundary-matrix.md",
        reviews / "second-batch-2b-golden-fixture-plan.md",
        reviews / "second-batch-2b-red-team.md",
    )
