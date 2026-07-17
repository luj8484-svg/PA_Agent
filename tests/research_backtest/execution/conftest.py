from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "test_id(value): frozen MASTER_TEST_REGISTRY_V1 identity")
    config.addinivalue_line(
        "markers", "requirement_ids(*values): non-empty frozen 2B Requirement bindings"
    )
