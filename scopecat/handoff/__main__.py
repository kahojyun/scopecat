"""Command-line smoke entrypoint for the handoff prototype."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.handoff import open_package, write_inspection_artifact


def _summary(package_dir: Path, *, html_dir: Path | None = None) -> dict[str, object]:
    package = open_package(package_dir)
    artifact = None
    if html_dir is not None:
        artifact = write_inspection_artifact(package, output_dir=html_dir)
    return {
        "package_id": package.package_id,
        "display_name": package.display_name,
        "preview_classification": package.preview_classification,
        "measurement_ids": list(package.measurement_ids),
        "finding_count": len(package.findings),
        "linked_context_count": len(package.linked_context),
        "html_artifact": artifact["html_artifact"] if artifact is not None else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scopecat.handoff",
        description="Open a Scopecat handoff package for read-only local orientation.",
    )
    parser.add_argument("package_dir", type=Path)
    parser.add_argument(
        "--html-dir",
        type=Path,
        help="Write a local static HTML inspection artifact in this directory.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(_summary(args.package_dir, html_dir=args.html_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
