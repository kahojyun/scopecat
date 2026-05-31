"""Command-line smoke entrypoint for Measurement Records prototypes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.measurement_records.operator_review import (
    MeasurementRecordOperatorReviewRequest,
    review_measurement_records_from_request,
)
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


def _operator_review(args: argparse.Namespace) -> dict[str, object]:
    running_request = None
    if args.running_record_id is not None:
        running_request = MeasurementRecordRunningInspectionRequest(
            request_id=f"{args.request_id}-running-inspection",
            record_id=args.running_record_id,
            record_dir=args.running_record_dir,
            writer_receipt_path=args.running_writer_receipt_path,
            update_receipt_paths=tuple(args.running_update_receipt_path or ()),
            expected_total_rows=args.running_expected_total_rows,
            preview_row_limit=args.preview_row_limit,
        )
    request = MeasurementRecordOperatorReviewRequest(
        request_id=args.request_id,
        records_dir=args.records_dir,
        selected_record_id=args.selected_record_id,
        verify_source_digests=not args.skip_source_digest_verification,
        running_inspection_requests=() if running_request is None else (running_request,),
        latest_row_limit=args.latest_row_limit,
    )
    return review_measurement_records_from_request(
        request,
        storage_root=args.storage_root,
    ).to_dict()


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

    review_parser = subparsers.add_parser(
        "operator-review",
        help="Print a read-only local operator review over visible measurement records.",
    )
    review_parser.add_argument("--storage-root", type=Path, required=True)
    review_parser.add_argument("--request-id", required=True)
    review_parser.add_argument("--records-dir", default="records")
    review_parser.add_argument("--selected-record-id")
    review_parser.add_argument(
        "--skip-source-digest-verification",
        action="store_true",
        help="Skip catalog source-digest checks for projected read models.",
    )
    review_parser.add_argument("--running-record-id")
    review_parser.add_argument("--running-record-dir")
    review_parser.add_argument("--running-writer-receipt-path")
    review_parser.add_argument(
        "--running-update-receipt-path",
        action="append",
        default=[],
        help="Record-local update receipt path for the optional running inspection.",
    )
    review_parser.add_argument("--running-expected-total-rows", type=int)
    review_parser.add_argument("--preview-row-limit", type=int, default=5)
    review_parser.add_argument("--latest-row-limit", type=int, default=3)

    args = parser.parse_args(argv)
    if args.command == "running-inspection-summary":
        payload = _running_inspection_summary(args)
    elif args.command == "operator-review":
        if args.running_record_id is not None and (
            args.running_record_dir is None or args.running_writer_receipt_path is None
        ):
            parser.error(
                "--running-record-dir and --running-writer-receipt-path are required "
                "with --running-record-id"
            )
        payload = _operator_review(args)
    else:  # pragma: no cover - argparse enforces known commands.
        parser.error("unsupported command")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
