"""``python -m eval`` entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys

from .runner import run


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    p.add_argument("--only", metavar="CHANNEL|CATEGORY", help="run only 'chat', 'schedule', or one category")
    p.add_argument("--id", dest="one_id", metavar="SCENARIO_ID", help="run a single scenario by id")
    args = p.parse_args()

    summary = asyncio.run(run(only=args.only, one_id=args.one_id))
    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
