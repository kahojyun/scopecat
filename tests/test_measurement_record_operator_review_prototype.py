from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordAppendChunk,
    MeasurementRecordCreationRequest,
    MeasurementRecordFinalizationRequest,
    MeasurementRecordInProgressUpdateRequest,
    MeasurementRecordOperatorReviewReceiptRequest,
    MeasurementRecordOperatorReviewRequest,
    MeasurementRecordReadModelProjectionRequest,
    MeasurementRecordReadRequest,
    MeasurementRecordRunningInspectionRequest,
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    append_in_progress_measurement_record_from_request,
    create_measurement_record_from_request,
    finalize_measurement_record_from_read_view,
    project_measurement_record_read_model_from_read_view,
    read_created_record_primary_table_from_request,
    review_measurement_records,
    review_measurement_records_from_request,
    save_measurement_record_operator_review_receipt,
    summarize_measurement_record_operator_review_receipt,
    write_created_record_primary_data_from_request,
)
from scopecat.measurement_records.__main__ import main as measurement_records_main
from scopecat.measurement_records.operator_review import (
    OPERATOR_REVIEW_POLICY,
    OPERATOR_REVIEW_RECEIPT_SCHEMA,
    OPERATOR_REVIEW_SCHEMA,
)

ROOT = Path(__file__).resolve().parents[1]
CHUNK_FIXTURE = ROOT / "tests" / "fixtures" / "measurement_storage_writer" / "basic_append"


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _writer_chunk_one() -> MeasurementRecordWriterChunk:
    path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    return MeasurementRecordWriterChunk(
        chunk_id="chunk-3101-1",
        sequence=1,
        event_id="evt-3101-data-1",
        content_ref="chunks/chunk-1.csv",
        declared_digest=_digest(path),
        size_bytes=path.stat().st_size,
        rows_recorded=3,
        total_rows_recorded=3,
    )


def _writer_chunk_two() -> MeasurementRecordWriterChunk:
    path = CHUNK_FIXTURE / "chunks" / "chunk-2.csv"
    return MeasurementRecordWriterChunk(
        chunk_id="chunk-3101-2",
        sequence=2,
        event_id="evt-3101-data-2",
        content_ref="chunks/chunk-2.csv",
        declared_digest=_digest(path),
        size_bytes=path.stat().st_size,
        rows_recorded=2,
        total_rows_recorded=5,
    )


def _append_chunk_two() -> MeasurementRecordAppendChunk:
    path = CHUNK_FIXTURE / "chunks" / "chunk-2.csv"
    return MeasurementRecordAppendChunk(
        chunk_id="chunk-3101-2",
        sequence=2,
        event_id="evt-3101-data-2",
        content_ref="chunks/chunk-2.csv",
        declared_digest=_digest(path),
        size_bytes=path.stat().st_size,
        rows_recorded=2,
        previous_total_rows_recorded=3,
        total_rows_recorded=5,
    )


def _record_dir(record_id: str) -> str:
    return f"records/{record_id}"


def _read_request(record_id: str = "run-3101-rabi") -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id=f"read-primary-{record_id}",
        record_id=record_id,
        record_dir=_record_dir(record_id),
        writer_receipt_path=f"{_record_dir(record_id)}/writer-receipt.json",
        preview_row_limit=2,
    )


def _finalization_request(record_id: str = "run-3101-rabi") -> MeasurementRecordFinalizationRequest:
    return MeasurementRecordFinalizationRequest(
        request_id=f"finalize-{record_id}",
        approval_state="approved",
        record_id=record_id,
        record_dir=_record_dir(record_id),
        writer_receipt_path=f"{_record_dir(record_id)}/writer-receipt.json",
        finalization_receipt_path=f"{_record_dir(record_id)}/finalization-receipt.json",
        final_state="complete",
    )


def _projection_request(
    record_id: str = "run-3101-rabi",
) -> MeasurementRecordReadModelProjectionRequest:
    return MeasurementRecordReadModelProjectionRequest(
        request_id=f"project-read-model-{record_id}",
        approval_state="approved",
        record_id=record_id,
        record_dir=_record_dir(record_id),
        writer_receipt_path=f"{_record_dir(record_id)}/writer-receipt.json",
        finalization_receipt_path=f"{_record_dir(record_id)}/finalization-receipt.json",
        read_model_path=f"{_record_dir(record_id)}/record-read-model.json",
    )


def _running_request(**overrides: object) -> MeasurementRecordRunningInspectionRequest:
    record_id = str(overrides.pop("record_id", "run-3101-rabi"))
    values = {
        "request_id": f"inspect-{record_id}",
        "record_id": record_id,
        "record_dir": _record_dir(record_id),
        "writer_receipt_path": f"{_record_dir(record_id)}/writer-receipt.json",
        "update_receipt_paths": (f"{_record_dir(record_id)}/updates/update-3101-2.json",),
        "expected_total_rows": 5,
        "preview_row_limit": 5,
    }
    values.update(overrides)
    return MeasurementRecordRunningInspectionRequest(**values)


def _operator_request(**overrides: object) -> MeasurementRecordOperatorReviewRequest:
    values = {
        "request_id": "operator-review-records",
        "records_dir": "records",
        "selected_record_id": "run-3101-rabi",
        "verify_source_digests": True,
        "running_inspection_requests": (),
        "latest_row_limit": 2,
    }
    values.update(overrides)
    return MeasurementRecordOperatorReviewRequest(**values)


def _operator_source(**overrides: object) -> dict:
    return {
        "operator_review_schema": OPERATOR_REVIEW_SCHEMA,
        "operator_review_policy": OPERATOR_REVIEW_POLICY,
        "operator_review_request": _operator_request(**overrides).to_dict(),
    }


def _receipt_request(**overrides: object) -> MeasurementRecordOperatorReviewReceiptRequest:
    values = {
        "request_id": "save-operator-review-records",
        "approval_state": "approved",
        "review_receipt_path": "operator-reviews/review-001.json",
        "operator_disposition": "recorded_for_continuation",
        "operator_reason": "continue after refreshing missing read models",
    }
    values.update(overrides)
    return MeasurementRecordOperatorReviewReceiptRequest(**values)


def _populate_record(
    storage_root: Path,
    content_root: Path,
    *,
    record_id: str = "run-3101-rabi",
    state: str,
    chunks: tuple[MeasurementRecordWriterChunk, ...],
    expected_rows: int,
) -> None:
    create_run = create_measurement_record_from_request(
        MeasurementRecordCreationRequest(
            request_id=f"create-record-{record_id}",
            approval_state="approved",
            record_id=record_id,
            record_dir=_record_dir(record_id),
            initial_lifecycle_state=state,
            creation_source_kind="writer",
        ),
        storage_root=storage_root,
    )
    if not create_run.created:
        raise AssertionError(create_run.to_dict())

    write_run = write_created_record_primary_data_from_request(
        MeasurementRecordWriterRequest(
            request_id=f"write-primary-{record_id}",
            approval_state="approved",
            record_id=record_id,
            record_dir=_record_dir(record_id),
            primary_data_path=f"{_record_dir(record_id)}/primary.csv",
            writer_receipt_path=f"{_record_dir(record_id)}/writer-receipt.json",
            primary_data_format="csv_table",
            expected_rows=expected_rows,
            chunks=chunks,
        ),
        storage_root=storage_root,
        content_root=content_root,
    )
    if not write_run.written:
        raise AssertionError(write_run.to_dict())


def _read_view(storage_root: Path, record_id: str = "run-3101-rabi"):
    return read_created_record_primary_table_from_request(
        _read_request(record_id),
        storage_root=storage_root,
    )


def _populate_projected_record(
    storage_root: Path,
    content_root: Path,
    *,
    record_id: str = "run-3101-rabi",
) -> None:
    _populate_record(
        storage_root,
        content_root,
        record_id=record_id,
        state="created",
        chunks=(_writer_chunk_one(), _writer_chunk_two()),
        expected_rows=5,
    )
    finalize_run = finalize_measurement_record_from_read_view(
        _finalization_request(record_id),
        read_view=_read_view(storage_root, record_id),
        storage_root=storage_root,
    )
    if not finalize_run.finalized:
        raise AssertionError(finalize_run.to_dict())
    projection_run = project_measurement_record_read_model_from_read_view(
        _projection_request(record_id),
        read_view=_read_view(storage_root, record_id),
        storage_root=storage_root,
    )
    if not projection_run.projected:
        raise AssertionError(projection_run.to_dict())


def _populate_in_progress_with_append(
    storage_root: Path,
    content_root: Path,
    *,
    record_id: str = "run-3101-rabi",
) -> None:
    _populate_record(
        storage_root,
        content_root,
        record_id=record_id,
        state="in_progress",
        chunks=(_writer_chunk_one(),),
        expected_rows=3,
    )
    append_run = append_in_progress_measurement_record_from_request(
        MeasurementRecordInProgressUpdateRequest(
            request_id=f"append-{record_id}",
            approval_state="approved",
            update_id="update-3101-2",
            record_id=record_id,
            record_dir=_record_dir(record_id),
            writer_receipt_path=f"{_record_dir(record_id)}/writer-receipt.json",
            previous_update_receipt_path=None,
            append_segment_path=f"{_record_dir(record_id)}/segments/chunk-2.csv",
            update_receipt_path=f"{_record_dir(record_id)}/updates/update-3101-2.json",
            primary_data_format="csv_table",
            expected_total_rows=5,
            append_chunk=_append_chunk_two(),
        ),
        storage_root=storage_root,
        content_root=content_root,
    )
    if not append_run.updated:
        raise AssertionError(append_run.to_dict())


def _saved_operator_review_receipt() -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_root = Path(temp_dir) / "storage"
        content_root = Path(temp_dir) / "content"
        storage_root.mkdir()
        shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
        _populate_projected_record(storage_root, content_root)
        review_run = review_measurement_records_from_request(
            _operator_request(),
            storage_root=storage_root,
        )
        save_run = save_measurement_record_operator_review_receipt(
            _receipt_request(),
            operator_review=review_run,
            storage_root=storage_root,
        )
        if not save_run.saved:
            raise AssertionError(save_run.to_dict())
        return json.loads(
            (storage_root / "operator-reviews" / "review-001.json").read_text(encoding="utf-8")
        )


class MeasurementRecordOperatorReviewPrototypeTest(unittest.TestCase):
    def test_operator_review_lists_catalog_and_selected_record_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            before = read_model_path.read_text(encoding="utf-8")

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            after = read_model_path.read_text(encoding="utf-8")

        payload = run.to_dict()
        self.assertEqual(run.classification, "measurement_record_operator_review_ready")
        self.assertEqual(payload["catalog"]["entry_count"], 1)
        self.assertEqual(payload["selected_record"]["source"], "catalog")
        self.assertEqual(payload["selected_record"]["record"]["lifecycle_state"], "complete")
        self.assertEqual(payload["next_action"], "review_selected_record_summary")
        self.assertEqual(payload["review_findings"], [])
        self.assertEqual(after, before)
        self.assertIn("storage_mutation", payload["workflow"]["does_not_claim"])

    def test_operator_review_can_surface_selected_running_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_with_append(storage_root, content_root)

            run = review_measurement_records_from_request(
                _operator_request(running_inspection_requests=(_running_request(),)),
                storage_root=storage_root,
            )

        payload = run.to_dict()
        self.assertEqual(run.classification, "measurement_record_operator_review_ready")
        self.assertEqual(payload["catalog"]["entry_count"], 0)
        self.assertEqual(payload["selected_record"]["source"], "running_inspection")
        self.assertEqual(
            payload["selected_record"]["inspection"]["visible_rows_recorded"],
            5,
        )
        self.assertEqual(
            payload["next_action"],
            "ready_for_later_finalization_decision",
        )

    def test_operator_review_keeps_mixed_record_findings_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(
                storage_root,
                content_root,
                record_id="run-3101-rabi",
            )
            _populate_in_progress_with_append(
                storage_root,
                content_root,
                record_id="run-4101-t1",
            )
            _populate_record(
                storage_root,
                content_root,
                record_id="run-9999-needs-review",
                state="created",
                chunks=(_writer_chunk_one(),),
                expected_rows=3,
            )

            run = review_measurement_records_from_request(
                _operator_request(
                    selected_record_id="run-4101-t1",
                    running_inspection_requests=(_running_request(record_id="run-4101-t1"),),
                ),
                storage_root=storage_root,
            )

        payload = run.to_dict()
        self.assertEqual(run.classification, "measurement_record_operator_review_needed")
        self.assertEqual(payload["catalog"]["entry_count"], 1)
        self.assertEqual(payload["catalog"]["entries"][0]["record_id"], "run-3101-rabi")
        self.assertEqual(payload["selected_record"]["source"], "running_inspection")
        self.assertEqual(payload["selected_record"]["record"]["record_id"], "run-4101-t1")
        self.assertEqual(
            payload["selected_record"]["inspection"]["visible_rows_recorded"],
            5,
        )
        self.assertEqual(
            [finding["target"] for finding in payload["review_findings"]],
            ["records/run-9999-needs-review/record-read-model.json"],
        )
        self.assertEqual(payload["review_findings"][0]["code"], "read_model_missing")
        self.assertEqual(
            payload["next_action"],
            "review_measurement_record_operator_findings",
        )
        self.assertEqual(
            sorted(finding["target"] for finding in payload["catalog"]["review_findings"]),
            [
                "records/run-4101-t1/record-read-model.json",
                "records/run-9999-needs-review/record-read-model.json",
            ],
        )

    def test_raw_operator_review_uses_declared_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            run = review_measurement_records(
                _operator_source(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "measurement_record_operator_review_ready")
        self.assertEqual(run.to_dict()["selected_record"]["record"]["record_id"], "run-3101-rabi")

    def test_missing_selected_record_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = review_measurement_records_from_request(
                _operator_request(selected_record_id="missing-record"),
                storage_root=storage_root,
            )

        payload = run.to_dict()
        self.assertEqual(run.classification, "measurement_record_operator_review_needed")
        self.assertIsNone(payload["selected_record"])
        self.assertEqual(payload["review_findings"][0]["code"], "selected_record_not_visible")
        self.assertIn("declared_inputs", payload["review_findings"][0]["does_not_claim"])

    def test_operator_review_cli_prints_local_review_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = measurement_records_main(
                    [
                        "operator-review",
                        "--storage-root",
                        str(storage_root),
                        "--request-id",
                        "operator-review-cli",
                        "--selected-record-id",
                        "run-3101-rabi",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["artifact_posture"], "local_measurement_record_operator_review")
        self.assertEqual(
            payload["workflow"]["classification"],
            "measurement_record_operator_review_ready",
        )
        self.assertEqual(payload["selected_record"]["source"], "catalog")

    def test_operator_review_cli_accepts_raw_source_json_for_multiple_running_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            storage_root = temp_path / "storage"
            content_root = temp_path / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_with_append(
                storage_root,
                content_root,
                record_id="run-4101-t1",
            )
            _populate_in_progress_with_append(
                storage_root,
                content_root,
                record_id="run-4102-ramsey",
            )
            source_path = temp_path / "operator-review-source.json"
            source_path.write_text(
                json.dumps(
                    _operator_source(
                        selected_record_id="run-4102-ramsey",
                        running_inspection_requests=(
                            _running_request(record_id="run-4101-t1"),
                            _running_request(record_id="run-4102-ramsey"),
                        ),
                    )
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = measurement_records_main(
                    [
                        "operator-review",
                        "--storage-root",
                        str(storage_root),
                        "--source",
                        str(source_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            payload["workflow"]["classification"],
            "measurement_record_operator_review_ready",
        )
        self.assertEqual(len(payload["running_inspections"]), 2)
        self.assertEqual(payload["selected_record"]["source"], "running_inspection")
        self.assertEqual(payload["selected_record"]["record"]["record_id"], "run-4102-ramsey")

    def test_operator_review_cli_rejects_source_with_conflicting_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            storage_root = temp_path / "storage"
            storage_root.mkdir()
            source_path = temp_path / "operator-review-source.json"
            source_path.write_text(json.dumps(_operator_source()), encoding="utf-8")

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                measurement_records_main(
                    [
                        "operator-review",
                        "--storage-root",
                        str(storage_root),
                        "--source",
                        str(source_path),
                        "--request-id",
                        "conflicting-request",
                    ]
                )
            self.assertIn("--source cannot be combined", stderr.getvalue())

    def test_saves_operator_review_receipt_without_mutating_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model_before = read_model_path.read_text(encoding="utf-8")
            review_run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )

            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(),
                operator_review=review_run,
                storage_root=storage_root,
            )
            receipt_path = storage_root / "operator-reviews" / "review-001.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            summary = summarize_measurement_record_operator_review_receipt(receipt)
            read_model_after = read_model_path.read_text(encoding="utf-8")
            receipt_digest = _digest(receipt_path)

        self.assertEqual(save_run.classification, "saved_operator_review_receipt")
        self.assertTrue(save_run.saved)
        self.assertEqual(receipt["schema"], OPERATOR_REVIEW_RECEIPT_SCHEMA)
        self.assertEqual(
            receipt["operator_review"]["request"]["request_id"],
            "operator-review-records",
        )
        self.assertEqual(receipt["operator_disposition"]["state"], "recorded_for_continuation")
        self.assertEqual(summary["operator_review"]["selected_record_id"], "run-3101-rabi")
        self.assertEqual(
            summary["operator_review"]["next_action"], "review_selected_record_summary"
        )
        self.assertIn("retry_authority", summary["does_not_claim"])
        self.assertEqual(read_model_after, read_model_before)
        self.assertEqual(
            save_run.to_dict()["receipt"]["receipt_digest"],
            receipt_digest,
        )

    def test_operator_review_receipt_path_must_use_receipt_namespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "operator-reviews"):
            _receipt_request(review_receipt_path="records/run-3101-rabi/operator-review.json")

    def test_unapproved_operator_review_receipt_request_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            review_run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )

            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(approval_state="needs_review"),
                operator_review=review_run,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "operator-reviews" / "review-001.json").exists())

        self.assertEqual(save_run.classification, "blocked_before_operator_review_receipt")
        self.assertFalse(save_run.saved)

    def test_operator_review_receipt_collision_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            review_run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            receipt_path = storage_root / "operator-reviews" / "review-001.json"
            receipt_path.parent.mkdir()
            receipt_path.write_text("existing receipt", encoding="utf-8")

            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(),
                operator_review=review_run,
                storage_root=storage_root,
            )

            self.assertEqual(receipt_path.read_text(encoding="utf-8"), "existing receipt")

        self.assertEqual(save_run.classification, "blocked_before_operator_review_receipt")
        self.assertIn("already exists", save_run.save_error or "")
        self.assertNotIn("write_operator_review_receipt", save_run.to_dict()["workflow"]["steps"])

    def test_operator_review_receipt_summary_rejects_unsupported_disposition(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_disposition"]["state"] = "approve_refresh"
        receipt["receipt_request"]["operator_disposition"] = "approve_refresh"

        with self.assertRaisesRegex(ValueError, "operator_disposition"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_malformed_findings(self) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["review_findings"].append("read_model_missing")
        receipt["summary"]["review_finding_codes"].append("read_model_missing")

        with self.assertRaisesRegex(ValueError, "finding must be an object"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_tampered_policy(self) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review_receipt_policy"]["record_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "policy"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_inconsistent_summary(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["summary"]["next_action"] = "refresh_read_model"

        with self.assertRaisesRegex(ValueError, "next_action"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_cli_prints_continuation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            review_run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(),
                operator_review=review_run,
                storage_root=storage_root,
            )
            if not save_run.saved:
                raise AssertionError(save_run.to_dict())
            receipt_path = storage_root / "operator-reviews" / "review-001.json"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = measurement_records_main(
                    [
                        "operator-review-receipt-summary",
                        "--receipt-path",
                        str(receipt_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            payload["summary_schema"],
            "scopecat.measurement_record_operator_review_receipt_summary.v0",
        )
        self.assertEqual(payload["operator_review"]["selected_record_id"], "run-3101-rabi")
        self.assertEqual(
            payload["receipt"]["operator_disposition"],
            "recorded_for_continuation",
        )
        self.assertIn("continuation_authority", payload["summary_policy"])


if __name__ == "__main__":
    unittest.main()
