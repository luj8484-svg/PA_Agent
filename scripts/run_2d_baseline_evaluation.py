from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from pa_agent.research_2d.runner import run_baseline_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run approved deterministic 2D baseline evaluation"
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    commit = (
        args.code_commit
        or subprocess.run(
            ("git", "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    output = run_baseline_evaluation(
        root=args.data_root.resolve(),
        output_root=args.output_root.resolve(),
        code_commit=commit,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
