from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pa_agent.research_backtest.testing.registry import (
    ImplementedTest,
    RegistryValidationError,
    default_document_paths,
    load_documented_master_registry,
    validate_registry,
)


class MetadataCollector:
    def __init__(self) -> None:
        self.tests: list[ImplementedTest] = []
        self.errors: list[str] = []

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            test_ids = [marker.args for marker in item.iter_markers("test_id")]
            requirements = [marker.args for marker in item.iter_markers("requirement_ids")]
            if len(test_ids) != 1 or len(test_ids[0]) != 1:
                self.errors.append(f"{item.nodeid}: requires exactly one test_id")
                continue
            if len(requirements) != 1 or not requirements[0]:
                self.errors.append(f"{item.nodeid}: requires one non-empty requirement_ids marker")
                continue
            try:
                self.tests.append(ImplementedTest(str(test_ids[0][0]), tuple(requirements[0])))
            except ValueError as exc:
                self.errors.append(f"{item.nodeid}: {exc}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    collector = MetadataCollector()
    exit_code = pytest.main(
        ["tests/research_backtest/execution", "--collect-only", "-q"],
        plugins=[collector],
    )
    if exit_code not in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED}:
        return int(exit_code)
    if collector.errors:
        raise RegistryValidationError("; ".join(collector.errors))
    documented = load_documented_master_registry(default_document_paths(root))
    report = validate_registry(documented, tuple(collector.tests))
    print(
        f"MASTER_TEST_REGISTRY_V1 PASS: documented={report.documented_count} "
        f"implemented={report.implemented_count} requirements={report.requirement_count}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistryValidationError as exc:
        print(f"MASTER_TEST_REGISTRY_V1 FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
