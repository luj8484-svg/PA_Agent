from __future__ import annotations

import argparse
import shutil
from decimal import Decimal
from pathlib import Path

from pa_agent.research_2d.archive import archive_failed_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive an accepted failed-baseline OOS result")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--engine-peak-observed-drawdown", type=Decimal, required=True)
    args = parser.parse_args()
    target = archive_failed_baseline(
        args.source,
        args.output_root,
        engine_peak_observed_drawdown=args.engine_peak_observed_drawdown,
    )
    zip_path = Path(shutil.make_archive(str(target), "zip", target))
    print(target)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
