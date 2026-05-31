"""Command-line smoke entrypoint for Measurement Records prototypes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scopecat.measurement_records.operator_review import (
    MeasurementRecordOperatorReviewRequest,
    review_measurement_records,
    review_measurement_records_from_request,
    summarize_measurement_record_operator_review_receipt,
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
    if args.source is not None:
        source = json.loads(args.source.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            raise ValueError("operator review source JSON must be an object")
        return review_measurement_records(source, storage_root=args.storage_root).to_dict()
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


def _operator_review_receipt_summary(args: argparse.Namespace) -> dict[str, object]:
    receipt = json.loads(args.receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("operator review receipt JSON must be an object")
    return summarize_measurement_record_operator_review_receipt(receipt)


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
    review_parser.add_argument(
        "--source",
        type=Path,
        help="JSON source matching the operator-review raw source schema.",
    )
    review_parser.add_argument("--request-id")
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

    receipt_parser = subparsers.add_parser(
        "operator-review-receipt-summary",
        help="Print a compact summary for a saved operator-review receipt.",
    )
    receipt_parser.add_argument("--receipt-path", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "running-inspection-summary":
        payload = _running_inspection_summary(args)
    elif args.command == "operator-review":
        if args.source is None and args.request_id is None:
            parser.error("--request-id is required unless --source is provided")
        if args.source is not None:
            ignored = []
            for name, value, default in (
                ("--request-id", args.request_id, None),
                ("--records-dir", args.records_dir, "records"),
                ("--selected-record-id", args.selected_record_id, None),
                (
                    "--skip-source-digest-verification",
                    args.skip_source_digest_verification,
                    False,
                ),
                ("--running-record-id", args.running_record_id, None),
                ("--running-record-dir", args.running_record_dir, None),
                (
                    "--running-writer-receipt-path",
                    args.running_writer_receipt_path,
                    None,
                ),
                (
                    "--running-update-receipt-path",
                    args.running_update_receipt_path,
                    [],
                ),
                (
                    "--running-expected-total-rows",
                    args.running_expected_total_rows,
                    None,
                ),
                ("--preview-row-limit", args.preview_row_limit, 5),
                ("--latest-row-limit", args.latest_row_limit, 3),
            ):
                if value != default:
                    ignored.append(name)
            if ignored:
                parser.error(
                    "--source cannot be combined with request-shaping flags: " + ", ".join(ignored)
                )
        if (
            args.source is None
            and args.running_record_id is not None
            and (args.running_record_dir is None or args.running_writer_receipt_path is None)
        ):
            parser.error(
                "--running-record-dir and --running-writer-receipt-path are required "
                "with --running-record-id"
            )
        if args.source is None and args.running_record_id is None:
            ignored_running = []
            for name, value, default in (
                ("--running-record-dir", args.running_record_dir, None),
                (
                    "--running-writer-receipt-path",
                    args.running_writer_receipt_path,
                    None,
                ),
                ("--running-update-receipt-path", args.running_update_receipt_path, []),
                (
                    "--running-expected-total-rows",
                    args.running_expected_total_rows,
                    None,
                ),
            ):
                if value != default:
                    ignored_running.append(name)
            if ignored_running:
                parser.error(
                    "--running-record-id is required with running inspection flags: "
                    + ", ".join(ignored_running)
                )
        payload = _operator_review(args)
    elif args.command == "operator-review-receipt-summary":
        payload = _operator_review_receipt_summary(args)
    else:  # pragma: no cover - argparse enforces known commands.
        parser.error("unsupported command")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
