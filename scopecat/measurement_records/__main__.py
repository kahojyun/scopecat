"""Command-line smoke entrypoint for Measurement Records prototypes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.measurement_records.running_inspection import (
    MeasurementRecordRunningInspectionRequest,
    inspect_running_measurement_record_from_request,
    summarize_running_measurement_inspection,
)


def _running_inspection_summary(args: argparse.Namespace) -> dict[str, object]:
    request = MeasurementRecordRunningInspectionRequest(
        request_id=args.request_id,
        record_id=args.record_id,
        record_dir=args.record_dir,
        writer_receipt_path=args.writer_receipt_path,
        update_receipt_paths=tuple(args.update_receipt_path or ()),
        expected_total_rows=args.expected_total_rows,
        preview_row_limit=args.preview_row_limit,
    )
    run = inspect_running_measurement_record_from_request(
        request,
        storage_root=args.storage_root,
    )
    return summarize_running_measurement_inspection(
        run,
        latest_row_limit=args.latest_row_limit,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scopecat.measurement_records",
        description="Run read-only Measurement Records prototype operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "running-inspection-summary",
        help="Print a compact local summary for an in-progress measurement record.",
    )
    inspect_parser.add_argument("--storage-root", type=Path, required=True)
    inspect_parser.add_argument("--request-id", required=True)
    inspect_parser.add_argument("--record-id", required=True)
    inspect_parser.add_argument("--record-dir", required=True)
    inspect_parser.add_argument("--writer-receipt-path", required=True)
    inspect_parser.add_argument(
        "--update-receipt-path",
        action="append",
        default=[],
        help="Record-local update receipt path. Repeat to inspect multiple append receipts.",
    )
    inspect_parser.add_argument("--expected-total-rows", type=int)
    inspect_parser.add_argument("--preview-row-limit", type=int, default=5)
    inspect_parser.add_argument("--latest-row-limit", type=int, default=3)

    args = parser.parse_args(argv)
    if args.command == "running-inspection-summary":
        payload = _running_inspection_summary(args)
    else:  # pragma: no cover - argparse enforces known commands.
        parser.error("unsupported command")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
