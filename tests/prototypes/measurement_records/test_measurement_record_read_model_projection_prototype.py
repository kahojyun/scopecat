from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordCreationRequest,
    MeasurementRecordFinalizationRequest,
    MeasurementRecordReadModelProjectionRequest,
    MeasurementRecordReadRequest,
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    create_measurement_record_from_request,
    finalize_measurement_record_from_read_view,
    project_measurement_record_read_model,
    project_measurement_record_read_model_from_read_view,
    read_created_record_primary_table_from_request,
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


def _chunk_one() -> MeasurementRecordWriterChunk:
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


def _chunk_two() -> MeasurementRecordWriterChunk:
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


def _read_request() -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id="read-primary-run-3101-rabi",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
        preview_row_limit=2,
    )


def _read_source() -> dict:
    return {
        "read_request": _read_request().to_dict(),
    }


def _finalization_request(**overrides: object) -> MeasurementRecordFinalizationRequest:
    values = {
        "request_id": "finalize-run-3101-rabi",
        "approval_state": "approved",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "finalization_receipt_path": "records/run-3101-rabi/finalization-receipt.json",
        "final_state": "complete",
    }
    values.update(overrides)
    return MeasurementRecordFinalizationRequest(**values)


def _projection_request(**overrides: object) -> MeasurementRecordReadModelProjectionRequest:
    values = {
        "request_id": "project-read-model-run-3101-rabi",
        "approval_state": "approved",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "finalization_receipt_path": "records/run-3101-rabi/finalization-receipt.json",
        "read_model_path": "records/run-3101-rabi/record-read-model.json",
    }
    values.update(overrides)
    return MeasurementRecordReadModelProjectionRequest(**values)


def _projection_source(**overrides: object) -> dict:
    return {
        "projection_request": _projection_request(**overrides).to_dict(),
        "read_view_source": _read_source(),
    }


def _populate_record(storage_root: Path, content_root: Path) -> None:
    create_run = create_measurement_record_from_request(
        MeasurementRecordCreationRequest(
            request_id="create-record-run-3101-rabi",
            approval_state="approved",
            record_id="run-3101-rabi",
            record_dir="records/run-3101-rabi",
            initial_lifecycle_state="created",
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
            expected_rows=5,
            chunks=(_chunk_one(), _chunk_two()),
        ),
        storage_root=storage_root,
        content_root=content_root,
    )
    if not write_run.written:
        raise AssertionError(write_run.to_dict())


def _read_view(storage_root: Path):
    return read_created_record_primary_table_from_request(
        _read_request(),
        storage_root=storage_root,
    )


def _finalize(storage_root: Path, **overrides: object) -> None:
    run = finalize_measurement_record_from_read_view(
        _finalization_request(**overrides),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not run.finalized:
        raise AssertionError(run.to_dict())


class MeasurementRecordReadModelProjectionPrototypeTest(unittest.TestCase):
    def test_projection_writes_read_model_without_replacing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            manifest_path = storage_root / "records" / "run-3101-rabi" / "record-manifest.json"
            manifest_before = json.loads(manifest_path.read_text(encoding="utf-8"))

            run = project_measurement_record_read_model_from_read_view(
                _projection_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(run.classification, "projected_read_model")
        self.assertTrue(run.projected)
        self.assertEqual(read_model["schema"], "measurement_record_read_model_v0")
        self.assertEqual(read_model["record"]["lifecycle_state"], "complete")
        self.assertEqual(read_model["record"]["creation_lifecycle_state"], "created")
        self.assertEqual(read_model["primary_data"]["observed_row_count"], 5)
        self.assertEqual(
            read_model["sources"]["finalization_receipt"]["path"],
            "records/run-3101-rabi/finalization-receipt.json",
        )
        self.assertEqual(
            set(read_model),
            {
                "schema",
                "record",
                "sources",
                "primary_data",
                "table",
                "review",
                "finalization",
                "projection",
            },
        )
        self.assertEqual(manifest_after, manifest_before)
        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "artifact_posture",
                "classification",
                "request",
                "read_view",
                "finalization_receipt",
                "projection",
            },
        )
        self.assertEqual(summary["classification"], "projected_read_model")

    def test_raw_source_projection_composes_read_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)

            run = project_measurement_record_read_model(
                _projection_source(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "projected_read_model")
        self.assertTrue(run.projected)

    def test_failed_finalization_projection_records_operator_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(
                storage_root,
                final_state="failed",
                operator_reason="operator stopped after reviewing failed acquisition",
            )

            run = project_measurement_record_read_model_from_read_view(
                _projection_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )
            read_model = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "projected_read_model")
        self.assertEqual(read_model["record"]["lifecycle_state"], "failed")
        self.assertEqual(
            read_model["finalization"]["operator_reason"],
            "operator stopped after reviewing failed acquisition",
        )

    def test_unapproved_projection_does_not_write_read_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)

            run = project_measurement_record_read_model_from_read_view(
                _projection_request(approval_state="needs_review"),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").exists()
            )

        self.assertEqual(run.classification, "blocked_before_projection")
        self.assertFalse(run.projected)

    def test_existing_read_model_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model_path.write_text("existing projection", encoding="utf-8")

            run = project_measurement_record_read_model_from_read_view(
                _projection_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

            self.assertEqual(read_model_path.read_text(encoding="utf-8"), "existing projection")

        self.assertEqual(run.classification, "blocked_before_projection")
        self.assertIn("target already exists", run.projection_error or "")

    def test_projection_write_failure_rolls_back_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            target = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"

            def failing_writer(path: Path, content: bytes) -> None:
                path.write_bytes(content)
                raise RuntimeError("simulated projection failure")

            run = project_measurement_record_read_model_from_read_view(
                _projection_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
                model_writer=failing_writer,
            )

            self.assertFalse(target.exists())

        self.assertEqual(run.classification, "blocked_before_projection")
        self.assertIn("simulated projection failure", run.projection_error or "")

    def test_request_must_match_read_view_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)

            with self.assertRaisesRegex(ValueError, "record_id"):
                project_measurement_record_read_model_from_read_view(
                    _projection_request(record_id="other-record"),
                    read_view=_read_view(storage_root),
                    storage_root=storage_root,
                )

    def test_finalization_receipt_must_match_read_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "finalization-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["finalization"]["evidence"]["table_row_count"] = 4
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "table row count"):
                project_measurement_record_read_model_from_read_view(
                    _projection_request(),
                    read_view=_read_view(storage_root),
                    storage_root=storage_root,
                )

    def test_read_model_path_must_be_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical"):
            _projection_request(read_model_path="records/run-3101-rabi/custom-read-model.json")

    def test_projection_paths_reject_parent_child_overlap(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            _projection_request(
                finalization_receipt_path=(
                    "records/run-3101-rabi/record-read-model.json/finalization-receipt.json"
                )
            )


if __name__ == "__main__":
    unittest.main()
