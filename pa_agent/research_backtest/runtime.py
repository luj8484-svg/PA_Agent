from __future__ import annotations

import platform
from dataclasses import dataclass

DETERMINISTIC_RESEARCH_RUNTIME_VERSION = "DETERMINISTIC_RESEARCH_RUNTIME_V1"
REQUIRED_IMPLEMENTATION = "CPython"
REQUIRED_VERSION = "3.12.13"


@dataclass(frozen=True, slots=True)
class ResearchRuntimeStatus:
    implementation: str
    version: str
    status: str
    runtime_version: str = DETERMINISTIC_RESEARCH_RUNTIME_VERSION


def runtime_status() -> ResearchRuntimeStatus:
    implementation = platform.python_implementation()
    version = platform.python_version()
    status = (
        "PASS"
        if (implementation, version) == (REQUIRED_IMPLEMENTATION, REQUIRED_VERSION)
        else "FAIL"
    )
    return ResearchRuntimeStatus(implementation, version, status)


def assert_deterministic_research_runtime() -> None:
    observed = runtime_status()
    if observed.status != "PASS":
        raise RuntimeError(
            f"{DETERMINISTIC_RESEARCH_RUNTIME_VERSION} requires "
            f"{REQUIRED_IMPLEMENTATION} {REQUIRED_VERSION}; "
            f"received {observed.implementation} {observed.version}"
        )
