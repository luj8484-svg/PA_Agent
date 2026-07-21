from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pa_agent.research_2d.runner import run_baseline_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run approved deterministic 2D baseline evaluation"
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--code-commit")
    parser.add_argument("--max-workers", type=int, choices=(1, 2, 6), default=1)
    parser.add_argument("--task-timeout-seconds", type=float, default=28_800)
    parser.add_argument("--no-progress-timeout-seconds", type=float, default=600)
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
        max_workers=args.max_workers,
        task_timeout_seconds=args.task_timeout_seconds,
        no_progress_timeout_seconds=args.no_progress_timeout_seconds,
    )
    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as error:
        task_key = getattr(error, "task_key", "PARENT")
        traceback_text = getattr(error, "traceback_text", "")
        if traceback_text:
            print(f"task_key={task_key}\n{traceback_text}", file=sys.stderr)
        raise
