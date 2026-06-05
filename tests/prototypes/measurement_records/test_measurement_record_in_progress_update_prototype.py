from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records.creation import (
    MeasurementRecordCreationRequest,
    create_measurement_record_from_request,
)
from scopecat.measurement_records.in_progress_update import (
    MeasurementRecordAppendChunk,
    MeasurementRecordInProgressUpdateRequest,
    append_in_progress_measurement_record_from_request,
)
from scopecat.measurement_records.running_inspection import (
    MeasurementRecordRunningInspectionRequest,
    inspect_running_measurement_record_from_request,
    summarize_running_measurement_inspection,
)
from scopecat.measurement_records.writer_integration import (
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    write_created_record_primary_data_from_request,
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


def _digest_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


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


def _append_chunk_two(**overrides: object) -> MeasurementRecordAppendChunk:
    path = CHUNK_FIXTURE / "chunks" / "chunk-2.csv"
    values = {
        "chunk_id": "chunk-3101-2",
        "sequence": 2,
        "event_id": "evt-3101-data-2",
        "content_ref": "chunks/chunk-2.csv",
        "declared_digest": _digest(path),
        "size_bytes": path.stat().st_size,
        "rows_recorded": 2,
        "previous_total_rows_recorded": 3,
        "total_rows_recorded": 5,
    }
    values.update(overrides)
    return MeasurementRecordAppendChunk(**values)


def _update_request(**overrides: object) -> MeasurementRecordInProgressUpdateRequest:
    values = {
        "request_id": "append-run-3101-rabi",
        "approval_state": "approved",
        "update_id": "update-3101-2",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "previous_update_receipt_path": None,
        "append_segment_path": "records/run-3101-rabi/segments/chunk-2.csv",
        "update_receipt_path": "records/run-3101-rabi/updates/update-3101-2.json",
        "primary_data_format": "csv_table",
        "expected_total_rows": 5,
        "append_chunk": _append_chunk_two(),
    }
    values.update(overrides)
    return MeasurementRecordInProgressUpdateRequest(**values)


def _update_source(**overrides: object) -> dict:
    return {
        "in_progress_update_request": _update_request(**overrides).to_dict(),
    }


def _inspection_request(**overrides: object) -> MeasurementRecordRunningInspectionRequest:
    values = {
        "request_id": "inspect-run-3101-rabi",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "update_receipt_paths": ("records/run-3101-rabi/updates/update-3101-2.json",),
        "expected_total_rows": 5,
        "preview_row_limit": 5,
    }
    values.update(overrides)
    return MeasurementRecordRunningInspectionRequest(**values)


def _inspection_source(**overrides: object) -> dict:
    return {
        "running_inspection_request": _inspection_request(**overrides).to_dict(),
    }


def _populate_in_progress_record(storage_root: Path, content_root: Path, *, state: str) -> None:
    create_run = create_measurement_record_from_request(
        MeasurementRecordCreationRequest(
            request_id="create-record-run-3101-rabi",
            approval_state="approved",
            record_id="run-3101-rabi",
            record_dir="records/run-3101-rabi",
            initial_lifecycle_state=state,
            creation_source_kind="writer",
        ),
        storage_root=storage_root,
    )
    if not create_run.created:
        raise AssertionError(create_run.to_dict())
    write_run = write_created_record_primary_data_from_request(
        MeasurementRecordWriterRequest(
            request_id="write-primary-run-3101-rabi",
            approval_state="approved",
            record_id="run-3101-rabi",
            record_dir="records/run-3101-rabi",
            primary_data_path="records/run-3101-rabi/primary.csv",
            writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
            primary_data_format="csv_table",
            expected_rows=3,
            chunks=(_writer_chunk_one(),),
        ),
        storage_root=storage_root,
        content_root=content_root,
    )
    if not write_run.written:
        raise AssertionError(write_run.to_dict())


class MeasurementRecordInProgressUpdatePrototypeTest(unittest.TestCase):
    def test_appends_segment_and_update_receipt_without_replacing_primary_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            original_primary = primary_path.read_text(encoding="utf-8")

            run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            segment_path = storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv"
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            updated_primary = primary_path.read_text(encoding="utf-8")
            segment_text = segment_path.read_text(encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(run.classification, "appended_to_in_progress_record")
        self.assertTrue(run.updated)
        self.assertEqual(updated_primary, original_primary)
        self.assertEqual(
            segment_text,
            (CHUNK_FIXTURE / "chunks" / "chunk-2.csv").read_text(encoding="utf-8"),
        )
        self.assertEqual(receipt["schema"], "measurement_record_update_receipt_v0")
        self.assertEqual(receipt["record"]["record_id"], "run-3101-rabi")
        self.assertEqual(receipt["append_chunk"]["previous_total_rows_recorded"], 3)
        self.assertEqual(receipt["append_chunk"]["total_rows_recorded"], 5)
        self.assertEqual(run.to_dict()["classification"], "appended_to_in_progress_record")
        self.assertEqual(
            [item["kind"] for item in run.to_dict()["in_progress_update"]["write_results"]],
            ["append_segment", "update_receipt"],
        )

    def test_unapproved_update_does_not_write_append_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")

            run = append_in_progress_measurement_record_from_request(
                _update_request(approval_state="needs_review"),
                storage_root=storage_root,
                content_root=content_root,
            )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse(
                (
                    storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
                ).exists()
            )

        self.assertEqual(run.classification, "blocked_before_in_progress_update")
        self.assertFalse(run.updated)

    def test_created_lifecycle_state_blocks_in_progress_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="created")

            with self.assertRaisesRegex(ValueError, "in_progress"):
                append_in_progress_measurement_record_from_request(
                    _update_request(),
                    storage_root=storage_root,
                    content_root=content_root,
                )

    def test_append_chunk_digest_mismatch_is_rejected_before_mutation(self) -> None:
        bad_chunk = _append_chunk_two(declared_digest="sha256:" + "a" * 64)
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")

            with self.assertRaisesRegex(ValueError, "digest"):
                append_in_progress_measurement_record_from_request(
                    _update_request(append_chunk=bad_chunk),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv").exists()
            )

    def test_update_receipt_failure_rolls_back_append_segment(self) -> None:
        def fail_receipt_write(path: Path, content: bytes) -> None:
            if path.name == "update-3101-2.json":
                raise OSError("simulated update receipt failure")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")

            run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
                file_writer=fail_receipt_write,
            )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv").exists()
            )
            self.assertFalse((storage_root / "records" / "run-3101-rabi" / "segments").exists())
            self.assertFalse((storage_root / "records" / "run-3101-rabi" / "updates").exists())

        self.assertEqual(run.classification, "rolled_back_after_in_progress_update_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("simulated update receipt failure", run.update_error or "")

    def test_running_inspection_reads_base_primary_plus_append_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())

            run = inspect_running_measurement_record_from_request(
                _inspection_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "in_progress_table_ready")
        self.assertEqual(run.table["row_count"], 5)
        self.assertEqual(run.progress["base_rows_recorded"], 3)
        self.assertEqual(run.progress["visible_rows_recorded"], 5)
        self.assertEqual(run.progress["remaining_rows"], 0)
        self.assertEqual(run.table["rows"][-1]["drive_amplitude"], "1.00")
        self.assertEqual(run.to_dict()["update_receipts"][0]["update_id"], "update-3101-2")

    def test_running_inspection_summary_reports_latest_rows_and_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            run = inspect_running_measurement_record_from_request(
                _inspection_request(),
                storage_root=storage_root,
            )

        summary = summarize_running_measurement_inspection(run, latest_row_limit=2)

        self.assertEqual(
            summary["summary_schema"],
            "scopecat.measurement_record_running_inspection_summary.v0",
        )
        self.assertEqual(summary["artifact_posture"], "local_record_running_inspection_summary")
        self.assertEqual(summary["inspection"]["visible_rows_recorded"], 5)
        self.assertEqual(summary["inspection"]["latest_row_limit"], 2)
        self.assertEqual(
            [row["drive_amplitude"] for row in summary["inspection"]["latest_visible_rows"]],
            ["0.75", "1.00"],
        )
        self.assertEqual(
            summary["inspection"]["next_action"],
            "ready_for_later_finalization_decision",
        )

    def test_running_inspection_reads_multiple_append_receipts_in_progression(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())
            second_append = append_in_progress_measurement_record_from_request(
                _update_request(
                    request_id="append-run-3101-rabi-third",
                    update_id="update-3101-3",
                    previous_update_receipt_path=(
                        "records/run-3101-rabi/updates/update-3101-2.json"
                    ),
                    append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                    update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                    expected_total_rows=6,
                    append_chunk=MeasurementRecordAppendChunk(
                        chunk_id="chunk-3101-3",
                        sequence=3,
                        event_id="evt-3101-data-3",
                        content_ref="chunks/chunk-3.csv",
                        declared_digest=_digest(chunk_three_path),
                        size_bytes=chunk_three_path.stat().st_size,
                        rows_recorded=1,
                        previous_total_rows_recorded=5,
                        total_rows_recorded=6,
                    ),
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not second_append.updated:
                raise AssertionError(second_append.to_dict())
            run = inspect_running_measurement_record_from_request(
                _inspection_request(
                    update_receipt_paths=(
                        "records/run-3101-rabi/updates/update-3101-2.json",
                        "records/run-3101-rabi/updates/update-3101-3.json",
                    ),
                    expected_total_rows=6,
                ),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "in_progress_table_ready")
        self.assertEqual(run.progress["append_receipts_observed"], 2)
        self.assertEqual(run.progress["visible_rows_recorded"], 6)
        self.assertEqual(run.table["rows"][-1]["drive_amplitude"], "1.25")
        self.assertEqual(
            [receipt["update_request"]["update_id"] for receipt in run.update_receipts],
            ["update-3101-2", "update-3101-3"],
        )

    def test_running_inspection_rejects_gap_between_multiple_append_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())
            second_append = append_in_progress_measurement_record_from_request(
                _update_request(
                    request_id="append-run-3101-rabi-third",
                    update_id="update-3101-3",
                    previous_update_receipt_path=(
                        "records/run-3101-rabi/updates/update-3101-2.json"
                    ),
                    append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                    update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                    expected_total_rows=6,
                    append_chunk=MeasurementRecordAppendChunk(
                        chunk_id="chunk-3101-3",
                        sequence=3,
                        event_id="evt-3101-data-3",
                        content_ref="chunks/chunk-3.csv",
                        declared_digest=_digest(chunk_three_path),
                        size_bytes=chunk_three_path.stat().st_size,
                        rows_recorded=1,
                        previous_total_rows_recorded=5,
                        total_rows_recorded=6,
                    ),
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not second_append.updated:
                raise AssertionError(second_append.to_dict())
            second_receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-3.json"
            )
            second_receipt = json.loads(second_receipt_path.read_text(encoding="utf-8"))
            second_receipt["append_chunk"]["previous_total_rows_recorded"] = 4
            second_receipt_path.write_text(json.dumps(second_receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contiguous"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(
                        update_receipt_paths=(
                            "records/run-3101-rabi/updates/update-3101-2.json",
                            "records/run-3101-rabi/updates/update-3101-3.json",
                        ),
                        expected_total_rows=6,
                    ),
                    storage_root=storage_root,
                )

    def test_running_inspection_rejects_broken_previous_receipt_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())
            second_append = append_in_progress_measurement_record_from_request(
                _update_request(
                    request_id="append-run-3101-rabi-third",
                    update_id="update-3101-3",
                    previous_update_receipt_path=(
                        "records/run-3101-rabi/updates/update-3101-2.json"
                    ),
                    append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                    update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                    expected_total_rows=6,
                    append_chunk=MeasurementRecordAppendChunk(
                        chunk_id="chunk-3101-3",
                        sequence=3,
                        event_id="evt-3101-data-3",
                        content_ref="chunks/chunk-3.csv",
                        declared_digest=_digest(chunk_three_path),
                        size_bytes=chunk_three_path.stat().st_size,
                        rows_recorded=1,
                        previous_total_rows_recorded=5,
                        total_rows_recorded=6,
                    ),
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not second_append.updated:
                raise AssertionError(second_append.to_dict())
            second_receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-3.json"
            )
            second_receipt = json.loads(second_receipt_path.read_text(encoding="utf-8"))
            second_receipt["update_request"]["previous_update_receipt_path"] = (
                "records/run-3101-rabi/updates/not-the-previous.json"
            )
            second_receipt_path.write_text(json.dumps(second_receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "previous update receipt path"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(
                        update_receipt_paths=(
                            "records/run-3101-rabi/updates/update-3101-2.json",
                            "records/run-3101-rabi/updates/update-3101-3.json",
                        ),
                        expected_total_rows=6,
                    ),
                    storage_root=storage_root,
                )

    def test_running_inspection_rejects_broken_previous_receipt_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())
            second_append = append_in_progress_measurement_record_from_request(
                _update_request(
                    request_id="append-run-3101-rabi-third",
                    update_id="update-3101-3",
                    previous_update_receipt_path=(
                        "records/run-3101-rabi/updates/update-3101-2.json"
                    ),
                    append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                    update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                    expected_total_rows=6,
                    append_chunk=MeasurementRecordAppendChunk(
                        chunk_id="chunk-3101-3",
                        sequence=3,
                        event_id="evt-3101-data-3",
                        content_ref="chunks/chunk-3.csv",
                        declared_digest=_digest(chunk_three_path),
                        size_bytes=chunk_three_path.stat().st_size,
                        rows_recorded=1,
                        previous_total_rows_recorded=5,
                        total_rows_recorded=6,
                    ),
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not second_append.updated:
                raise AssertionError(second_append.to_dict())
            second_receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-3.json"
            )
            second_receipt = json.loads(second_receipt_path.read_text(encoding="utf-8"))
            second_receipt["previous_update_receipt"]["update_id"] = "not-the-previous"
            second_receipt_path.write_text(json.dumps(second_receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "previous update receipt ref"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(
                        update_receipt_paths=(
                            "records/run-3101-rabi/updates/update-3101-2.json",
                            "records/run-3101-rabi/updates/update-3101-3.json",
                        ),
                        expected_total_rows=6,
                    ),
                    storage_root=storage_root,
                )

    def test_second_append_rejects_reused_previous_update_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())

            with self.assertRaisesRegex(ValueError, "update_id"):
                append_in_progress_measurement_record_from_request(
                    _update_request(
                        request_id="append-run-3101-rabi-third",
                        update_id="update-3101-2",
                        previous_update_receipt_path=(
                            "records/run-3101-rabi/updates/update-3101-2.json"
                        ),
                        append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                        update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                        expected_total_rows=6,
                        append_chunk=MeasurementRecordAppendChunk(
                            chunk_id="chunk-3101-3",
                            sequence=3,
                            event_id="evt-3101-data-3",
                            content_ref="chunks/chunk-3.csv",
                            declared_digest=_digest(chunk_three_path),
                            size_bytes=chunk_three_path.stat().st_size,
                            rows_recorded=1,
                            previous_total_rows_recorded=5,
                            total_rows_recorded=6,
                        ),
                    ),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-3.csv").exists()
            )

    def test_third_append_rejects_reused_embedded_previous_update_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            chunk_four_path = content_root / "chunks" / "chunk-4.csv"
            chunk_four_path.write_text("1.50,0.52\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            first_append = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not first_append.updated:
                raise AssertionError(first_append.to_dict())
            second_append = append_in_progress_measurement_record_from_request(
                _update_request(
                    request_id="append-run-3101-rabi-third",
                    update_id="update-3101-3",
                    previous_update_receipt_path=(
                        "records/run-3101-rabi/updates/update-3101-2.json"
                    ),
                    append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                    update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                    expected_total_rows=6,
                    append_chunk=MeasurementRecordAppendChunk(
                        chunk_id="chunk-3101-3",
                        sequence=3,
                        event_id="evt-3101-data-3",
                        content_ref="chunks/chunk-3.csv",
                        declared_digest=_digest(chunk_three_path),
                        size_bytes=chunk_three_path.stat().st_size,
                        rows_recorded=1,
                        previous_total_rows_recorded=5,
                        total_rows_recorded=6,
                    ),
                ),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not second_append.updated:
                raise AssertionError(second_append.to_dict())

            with self.assertRaisesRegex(ValueError, "previous receipt chain"):
                append_in_progress_measurement_record_from_request(
                    _update_request(
                        request_id="append-run-3101-rabi-fourth",
                        update_id="update-3101-2",
                        previous_update_receipt_path=(
                            "records/run-3101-rabi/updates/update-3101-3.json"
                        ),
                        append_segment_path="records/run-3101-rabi/segments/chunk-4.csv",
                        update_receipt_path="records/run-3101-rabi/updates/update-3101-4.json",
                        expected_total_rows=7,
                        append_chunk=MeasurementRecordAppendChunk(
                            chunk_id="chunk-3101-4",
                            sequence=4,
                            event_id="evt-3101-data-4",
                            content_ref="chunks/chunk-4.csv",
                            declared_digest=_digest(chunk_four_path),
                            size_bytes=chunk_four_path.stat().st_size,
                            rows_recorded=1,
                            previous_total_rows_recorded=6,
                            total_rows_recorded=7,
                        ),
                    ),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-4.csv").exists()
            )

    def test_second_append_requires_declared_previous_update_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            chunk_three_path = content_root / "chunks" / "chunk-3.csv"
            chunk_three_path.write_text("1.25,0.80\n", encoding="utf-8")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")

            with self.assertRaisesRegex(ValueError, "writer receipt rows_recorded"):
                append_in_progress_measurement_record_from_request(
                    _update_request(
                        request_id="append-run-3101-rabi-third",
                        update_id="update-3101-3",
                        append_segment_path="records/run-3101-rabi/segments/chunk-3.csv",
                        update_receipt_path="records/run-3101-rabi/updates/update-3101-3.json",
                        expected_total_rows=6,
                        append_chunk=MeasurementRecordAppendChunk(
                            chunk_id="chunk-3101-3",
                            sequence=3,
                            event_id="evt-3101-data-3",
                            content_ref="chunks/chunk-3.csv",
                            declared_digest=_digest(chunk_three_path),
                            size_bytes=chunk_three_path.stat().st_size,
                            rows_recorded=1,
                            previous_total_rows_recorded=5,
                            total_rows_recorded=6,
                        ),
                    ),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-3.csv").exists()
            )

    def test_running_inspection_reports_declared_progress_mismatch_as_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["append_chunk"]["total_rows_recorded"] = 4
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            run = inspect_running_measurement_record_from_request(
                _inspection_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "in_progress_table_review_needed")
        self.assertEqual(
            [finding["code"] for finding in run.review_findings], ["visible_row_count_mismatch"]
        )

    def test_running_inspection_rejects_append_segment_header_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            segment_content = b"drive_amplitude,excited_state_probability\n0.75,0.83\n1.00,0.94\n"
            segment_path = storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv"
            segment_path.write_bytes(segment_content)
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["append_segment"]["digest"] = _digest_bytes(segment_content)
            receipt["append_segment"]["size_bytes"] = len(segment_content)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must not repeat CSV header"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(),
                    storage_root=storage_root,
                )

    def test_running_inspection_rejects_append_segment_width_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            segment_content = b"0.75,0.83,extra\n1.00,0.94,extra\n"
            segment_path = storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv"
            segment_path.write_bytes(segment_content)
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["append_segment"]["digest"] = _digest_bytes(segment_content)
            receipt["append_segment"]["size_bytes"] = len(segment_content)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "append segment rows"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(),
                    storage_root=storage_root,
                )

    def test_running_inspection_rejects_empty_append_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            segment_content = b""
            segment_path = storage_root / "records" / "run-3101-rabi" / "segments" / "chunk-2.csv"
            segment_path.write_bytes(segment_content)
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["append_segment"]["digest"] = _digest_bytes(segment_content)
            receipt["append_segment"]["size_bytes"] = len(segment_content)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "append segment must contain rows"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(),
                    storage_root=storage_root,
                )

    def test_running_inspection_rejects_non_contiguous_update_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_in_progress_record(storage_root, content_root, state="in_progress")
            append_run = append_in_progress_measurement_record_from_request(
                _update_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            if not append_run.updated:
                raise AssertionError(append_run.to_dict())
            receipt_path = (
                storage_root / "records" / "run-3101-rabi" / "updates" / "update-3101-2.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["append_chunk"]["previous_total_rows_recorded"] = 2
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contiguous"):
                inspect_running_measurement_record_from_request(
                    _inspection_request(),
                    storage_root=storage_root,
                )
