"""Command-line smoke entrypoint for the handoff prototype."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.handoff import open_package


def _summary(package_dir: Path) -> dict[str, object]:
    package = open_package(package_dir)
    return {
        "package_id": package.package_id,
        "display_name": package.display_name,
        "preview_classification": package.preview_classification,
        "measurement_ids": list(package.measurement_ids),
        "finding_count": len(package.findings),
        "linked_context_count": len(package.linked_context),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scopecat.handoff",
        description="Open a Scopecat handoff package for read-only local orientation.",
    )
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(_summary(args.package_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
