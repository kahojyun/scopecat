"""Command-line smoke entrypoint for the handoff prototype."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.handoff import (
    open_package,
    summarize_import_workflow_receipt,
    write_inspection_artifact,
)


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


def _receipt_summary(receipt_path: Path) -> dict[str, object]:
    with receipt_path.open("r", encoding="utf-8") as handle:
        receipt = json.load(handle)
    return summarize_import_workflow_receipt(receipt).to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scopecat.handoff",
        description=(
            "Open a Scopecat handoff package or summarize a local import workflow receipt."
        ),
    )
    parser.add_argument("package_dir", type=Path, nargs="?")
    parser.add_argument(
        "--html-dir",
        type=Path,
        help="Write a local static HTML inspection artifact in this directory.",
    )
    parser.add_argument(
        "--receipt-summary",
        type=Path,
        help="Read a local import workflow receipt JSON file and print a continuation summary.",
    )
    args = parser.parse_args(argv)
    if args.receipt_summary is not None:
        if args.package_dir is not None:
            parser.error("package_dir is not accepted with --receipt-summary")
        if args.html_dir is not None:
            parser.error("--html-dir is not accepted with --receipt-summary")
        payload = _receipt_summary(args.receipt_summary)
    else:
        if args.package_dir is None:
            parser.error("package_dir is required unless --receipt-summary is provided")
        payload = _summary(args.package_dir, html_dir=args.html_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
