"""Side-effect-free command line boundary for deterministic research tooling."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import platform

VERSION = "0.1.0"
DEPENDENCY_DISTRIBUTIONS = ("pa-agent", "numpy", "pandas")


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _print_version() -> int:
    print(f"pa-research {VERSION}")
    return 0


def _validate_environment() -> int:
    from pa_agent.research_backtest.runtime import runtime_status

    importlib.import_module("pa_agent.research_data")
    importlib.import_module("pa_agent.research_backtest")
    observed = runtime_status()
    print(f"implementation={observed.implementation}")
    print(f"version={observed.version}")
    print(f"status={observed.status}")
    for distribution in DEPENDENCY_DISTRIBUTIONS:
        print(f"dependency.{distribution}={_distribution_version(distribution)}")
    print("research_data=OK")
    print("research_backtest=OK")
    print("llm_api_key_required=no")
    print("exchange_api_key_required=no")
    print("network_access=not_performed")
    return 0 if observed.status == "PASS" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pa-research",
        description="Deterministic BTC/ETH research utilities (no GUI, LLM, or trading access)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="show the research CLI version")
    subparsers.add_parser(
        "validate-environment",
        help="validate local research imports and dependency versions without network access",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        return _print_version()
    if args.command == "validate-environment":
        return _validate_environment()
    raise AssertionError(f"unreachable command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
