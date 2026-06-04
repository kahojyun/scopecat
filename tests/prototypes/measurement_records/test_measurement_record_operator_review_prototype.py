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
    MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME,
    MeasurementRecordAppendChunk,
    MeasurementRecordCreationRequest,
    MeasurementRecordFinalizationRequest,
    MeasurementRecordInProgressUpdateRequest,
    MeasurementRecordOperatorReviewReceiptRequest,
    MeasurementRecordOperatorReviewRequest,
    MeasurementRecordReadModelProjectionRequest,
    MeasurementRecordReadRequest,
    MeasurementRecordReference,
    MeasurementRecordReferenceRequest,
    MeasurementRecordRunningInspectionRequest,
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    append_in_progress_measurement_record_from_request,
    build_measurement_record_review_html,
    create_measurement_record_from_request,
    finalize_measurement_record_from_read_view,
    project_measurement_record_read_model_from_read_view,
    read_created_record_primary_table_from_request,
    record_measurement_record_references_from_request,
    review_measurement_records,
    review_measurement_records_from_request,
    save_measurement_record_operator_review_receipt,
    summarize_measurement_record_operator_review_receipt,
    write_created_record_primary_data_from_request,
    write_measurement_record_review_artifact,
)
from scopecat.measurement_records.__main__ import main as measurement_records_main
from scopecat.measurement_records.operator_review import (
    OPERATOR_REVIEW_POLICY,
    OPERATOR_REVIEW_RECEIPT_SCHEMA,
    OPERATOR_REVIEW_SCHEMA,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "measurement_storage_writer"
    / "basic_append"
)


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


def _recorded_reference_request(
    record_id: str = "run-3101-rabi",
) -> MeasurementRecordReferenceRequest:
    return MeasurementRecordReferenceRequest(
        request_id=f"record-references-{record_id}",
        approval_state="approved",
        record_id=record_id,
        record_dir=_record_dir(record_id),
        reference_set_id=f"references-{record_id}",
        references=(
            MeasurementRecordReference(
                reference_id="param-file-001",
                family="parameter_state",
                role="parameter_file",
                reference_kind="workspace_relative_path",
                reference_value=f"legacy-system/params/{record_id}.json",
                label="Legacy parameter file",
            ),
            MeasurementRecordReference(
                reference_id="analysis-summary-001",
                family="derived_artifact",
                role="preliminary_analysis_result",
                reference_kind="workspace_relative_path",
                reference_value=f"analysis/{record_id}/summary.csv",
                label="Initial analysis summary",
            ),
        ),
    )


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
        self.assertEqual(payload["recorded_references"]["entries"], [])
        self.assertEqual(payload["review_findings"], [])
        self.assertEqual(after, before)
        self.assertIn("storage_mutation", payload["workflow"]["does_not_claim"])

    def test_operator_review_surfaces_recorded_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            record_run = record_measurement_record_references_from_request(
                _recorded_reference_request(),
                storage_root=storage_root,
            )

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            html = build_measurement_record_review_html(run)

        payload = run.to_dict()
        self.assertTrue(record_run.recorded)
        self.assertEqual(
            payload["recorded_references"]["entries"][0]["record_id"],
            "run-3101-rabi",
        )
        self.assertEqual(
            [item["role"] for item in payload["recorded_references"]["entries"][0]["references"]],
            ["parameter_file", "preliminary_analysis_result"],
        )
        self.assertIn("Recorded References", html)
        self.assertIn("Legacy parameter file", html)
        self.assertIn("Initial analysis summary", html)

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

    def test_operator_review_surfaces_embedded_read_model_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            read_model["review"]["findings"] = [
                {
                    "code": "operator_review_required",
                    "message": "Read model carries an embedded review finding.",
                }
            ]
            read_model_path.write_text(json.dumps(read_model), encoding="utf-8")

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )

        payload = run.to_dict()
        self.assertEqual(run.classification, "measurement_record_operator_review_needed")
        self.assertEqual(
            payload["review_findings"][0]["code"],
            "read_model_review_findings_present",
        )
        self.assertEqual(
            payload["next_action"],
            "review_measurement_record_operator_findings",
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

    def test_operator_review_rejects_duplicate_running_record_snapshots(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique record_id"):
            _operator_request(
                running_inspection_requests=(
                    _running_request(record_id="run-4101-t1", request_id="inspect-t1-a"),
                    _running_request(record_id="run-4101-t1", request_id="inspect-t1-b"),
                )
            )

    def test_operator_review_rejects_duplicate_running_request_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique request_id"):
            _operator_request(
                running_inspection_requests=(
                    _running_request(record_id="run-4101-t1", request_id="inspect-duplicate"),
                    _running_request(record_id="run-4102-ramsey", request_id="inspect-duplicate"),
                )
            )

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

    def test_operator_review_html_renders_catalog_and_selected_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            html = build_measurement_record_review_html(run)

        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("Measurement Records Review", html)
        self.assertIn("run-3101-rabi", html)
        self.assertIn("measurement_record_operator_review_ready", html)
        self.assertIn("review_selected_record_summary", run.to_dict()["next_action"])
        self.assertNotIn("<script", html.lower())

    def test_operator_review_html_escapes_free_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            payload = run.to_dict()
            payload["review_findings"].append(
                {
                    "code": "unsafe_label",
                    "target": "records/run-3101-rabi",
                    "message": "Review <unsafe> label.",
                }
            )
            html = build_measurement_record_review_html(payload)

        self.assertIn("Review &lt;unsafe&gt; label.", html)
        self.assertNotIn("Review <unsafe> label.", html)

    def test_write_operator_review_artifact_returns_local_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            output_dir = Path(temp_dir) / "review"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )
            receipt = write_measurement_record_review_artifact(
                run,
                output_dir=output_dir,
            )
            artifact_path = Path(receipt["html_artifact"]["local_path"])
            html = artifact_path.read_text(encoding="utf-8")

        self.assertEqual(receipt["artifact_posture"], "review_summary")
        self.assertEqual(
            receipt["html_artifact"]["filename"],
            MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME,
        )
        self.assertFalse(receipt["html_artifact"]["durable_storage_member"])
        self.assertFalse(receipt["html_artifact"]["overwritten"])
        self.assertEqual(receipt["operator_review"]["catalog_entry_count"], 1)
        self.assertIn("run-3101-rabi", html)

    def test_write_operator_review_artifact_rejects_storage_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)

            run = review_measurement_records_from_request(
                _operator_request(),
                storage_root=storage_root,
            )

            with self.assertRaisesRegex(ValueError, "must not be in storage"):
                write_measurement_record_review_artifact(
                    run,
                    output_dir=storage_root / "review",
                )

    def test_operator_review_cli_can_write_local_html_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            html_dir = Path(temp_dir) / "review"
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
                        "--html-dir",
                        str(html_dir),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            html_path = Path(payload["html_artifact"]["local_path"])
            self.assertTrue(html_path.is_file())
            html = html_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["html_artifact"]["filename"], "measurement-record-review.html")
        self.assertIn("run-3101-rabi", html)

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

    def test_operator_review_cli_rejects_partial_running_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                measurement_records_main(
                    [
                        "operator-review",
                        "--storage-root",
                        str(storage_root),
                        "--request-id",
                        "operator-review-cli",
                        "--running-record-dir",
                        "records/run-3101-rabi",
                    ]
                )
            self.assertIn("--running-record-id is required", stderr.getvalue())

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

    def test_operator_review_receipt_summary_preserves_missing_selection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            review_run = review_measurement_records_from_request(
                _operator_request(selected_record_id="missing-record"),
                storage_root=storage_root,
            )

            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(),
                operator_review=review_run,
                storage_root=storage_root,
            )
            receipt = json.loads(
                (storage_root / "operator-reviews" / "review-001.json").read_text(encoding="utf-8")
            )
            summary = summarize_measurement_record_operator_review_receipt(receipt)

        self.assertTrue(save_run.saved)
        self.assertEqual(summary["operator_review"]["selected_record_id"], "missing-record")
        self.assertEqual(summary["operator_review"]["selected_record_source"], "not_visible")
        self.assertEqual(
            summary["operator_review"]["review_finding_codes"],
            ["selected_record_not_visible"],
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

    def test_operator_review_receipt_file_exists_race_does_not_delete_target(
        self,
    ) -> None:
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

            def racing_writer(path: Path, content: bytes) -> None:
                del content
                path.parent.mkdir()
                path.write_text("concurrent receipt", encoding="utf-8")
                raise FileExistsError(path)

            save_run = save_measurement_record_operator_review_receipt(
                _receipt_request(),
                operator_review=review_run,
                storage_root=storage_root,
                receipt_writer=racing_writer,
            )
            receipt_path = storage_root / "operator-reviews" / "review-001.json"
            receipt_text = receipt_path.read_text(encoding="utf-8")

        self.assertEqual(save_run.classification, "blocked_before_operator_review_receipt")
        self.assertEqual(receipt_text, "concurrent receipt")

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

    def test_operator_review_receipt_summary_rejects_tampered_non_claims(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["does_not_claim"] = ["record_mutation"]

        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            summarize_measurement_record_operator_review_receipt(receipt)

        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["workflow"]["does_not_claim"] = ["storage_mutation"]

        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_inconsistent_summary(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["summary"]["next_action"] = "refresh_read_model"

        with self.assertRaisesRegex(ValueError, "next_action"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_semantic_next_action_tampering(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["next_action"] = "select_record_for_review"
        receipt["summary"]["next_action"] = "select_record_for_review"

        with self.assertRaisesRegex(ValueError, "next_action must match"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_selected_record_tampering(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["selected_record"] = None
        receipt["operator_review"]["next_action"] = (
            "select_visible_record_or_update_declared_inputs"
        )
        receipt["summary"]["next_action"] = "select_visible_record_or_update_declared_inputs"

        with self.assertRaisesRegex(ValueError, "selected_record must match"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_missing_selection_without_finding(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["request"]["selected_record_id"] = "missing-record"
        receipt["operator_review"]["catalog"]["entries"] = []
        receipt["operator_review"]["selected_record"] = None
        receipt["operator_review"]["review_findings"] = []
        receipt["operator_review"]["workflow"]["classification"] = (
            "measurement_record_operator_review_ready"
        )
        receipt["operator_review"]["next_action"] = (
            "select_visible_record_or_update_declared_inputs"
        )
        receipt["summary"]["operator_review_classification"] = (
            "measurement_record_operator_review_ready"
        )
        receipt["summary"]["selected_record_id"] = "missing-record"
        receipt["summary"]["review_finding_codes"] = []
        receipt["summary"]["next_action"] = "select_visible_record_or_update_declared_inputs"

        with self.assertRaisesRegex(ValueError, "missing selected record"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_authority_action(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["operator_review"]["next_action"] = "approve_import"
        receipt["summary"]["next_action"] = "approve_import"

        with self.assertRaisesRegex(ValueError, "review-only action"):
            summarize_measurement_record_operator_review_receipt(receipt)

    def test_operator_review_receipt_summary_rejects_nonpublic_request_ids(
        self,
    ) -> None:
        receipt = _saved_operator_review_receipt()
        receipt["receipt_request"]["request_id"] = "records/private/request"

        with self.assertRaisesRegex(ValueError, "public-safe identifier"):
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
