"""Side-effect-free command line boundary for deterministic research tooling."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
from pathlib import Path

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


def _run_v2a_preflight_command(*, root: Path, output_root: Path, code_commit: str) -> Path:
    from pa_agent.research_v2a.walk_forward import run_v2a_candidate_preflight

    return run_v2a_candidate_preflight(
        root=root,
        output_root=output_root,
        code_commit=code_commit,
    )


def _run_v2a_walk_forward_command(
    *,
    root: Path,
    output_root: Path,
    code_commit: str,
    max_workers: int,
    hard_timeout_seconds: float,
    no_progress_timeout_seconds: None,
) -> Path:
    from pa_agent.research_v2a.walk_forward import run_v2a_walk_forward

    return run_v2a_walk_forward(
        root=root,
        output_root=output_root,
        code_commit=code_commit,
        max_workers=max_workers,
        hard_timeout_seconds=hard_timeout_seconds,
        no_progress_timeout_seconds=no_progress_timeout_seconds,
    )


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
    preflight = subparsers.add_parser(
        "v2a-preflight",
        help="run Candidate-only V2-A Preflight without minute replay",
    )
    preflight.add_argument("--data-root", type=Path, required=True)
    preflight.add_argument("--output-root", type=Path, required=True)
    preflight.add_argument("--code-commit", required=True)
    walk_forward = subparsers.add_parser(
        "v2a-walk-forward",
        help="run the explicitly approved bounded V2-A Walk-forward workflow",
    )
    walk_forward.add_argument("--data-root", type=Path, required=True)
    walk_forward.add_argument("--output-root", type=Path, required=True)
    walk_forward.add_argument("--code-commit", required=True)
    walk_forward.add_argument("--max-workers", type=int, choices=(2, 6), required=True)
    walk_forward.add_argument(
        "--hard-timeout-seconds",
        type=float,
        choices=(21_600,),
        default=21_600,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        return _print_version()
    if args.command == "validate-environment":
        return _validate_environment()
    if args.command == "v2a-preflight":
        output = _run_v2a_preflight_command(
            root=args.data_root,
            output_root=args.output_root,
            code_commit=args.code_commit,
        )
        print(output)
        return 0
    if args.command == "v2a-walk-forward":
        output = _run_v2a_walk_forward_command(
            root=args.data_root,
            output_root=args.output_root,
            code_commit=args.code_commit,
            max_workers=args.max_workers,
            hard_timeout_seconds=args.hard_timeout_seconds,
            no_progress_timeout_seconds=None,
        )
        print(output)
        return 0
    raise AssertionError(f"unreachable command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
