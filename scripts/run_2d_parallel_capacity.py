from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from pa_agent.research_2d.parallel import limit_numerical_threads

limit_numerical_threads()


def main() -> int:
    from pa_agent.research_2d.capacity import build_real_capacity_tasks, run_capacity_matrix

    parser = argparse.ArgumentParser(description="Measure Research 2D parallel capacity")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, nargs="+", choices=(1, 2, 6), default=(1, 2, 6))
    parser.add_argument("--duration-days", type=int, default=5)
    parser.add_argument("--task-timeout-seconds", type=float, default=3_600)
    parser.add_argument("--no-progress-timeout-seconds", type=float, default=600)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    commit = (
        args.code_commit
        or subprocess.run(
            ("git", "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    tasks = build_real_capacity_tasks(
        root=args.data_root.resolve(),
        code_commit=commit,
        duration_days=args.duration_days,
    )
    report = run_capacity_matrix(
        tasks,
        worker_counts=tuple(args.workers),
        task_timeout_seconds=args.task_timeout_seconds,
        no_progress_timeout_seconds=args.no_progress_timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
