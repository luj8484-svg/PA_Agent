from __future__ import annotations

import argparse
from pathlib import Path

from pa_agent.research_2d.attribution import AttributionInputMismatch, run_attribution


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only V1 failure attribution")
    parser.add_argument("--core-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        zip_path = run_attribution(
            core_root=args.core_root.resolve(),
            archive_root=args.archive_root.resolve(),
            data_root=args.data_root.resolve(),
            output_root=args.output_root.resolve(),
        )
    except AttributionInputMismatch as exc:
        print(exc)
        return 2
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
