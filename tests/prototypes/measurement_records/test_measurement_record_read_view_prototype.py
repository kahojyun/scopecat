from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordCreationRequest,
    MeasurementRecordReadRequest,
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    create_measurement_record_from_request,
    read_created_record_primary_table,
    read_created_record_primary_table_from_request,
    write_created_record_primary_data_from_request,
)
from scopecat.measurement_records.read_view import READ_VIEW_SCHEMA

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


def _read_request(**overrides: object) -> MeasurementRecordReadRequest:
    values = {
        "request_id": "read-primary-run-3101-rabi",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "preview_row_limit": 2,
    }
    values.update(overrides)
    return MeasurementRecordReadRequest(**values)


def _read_source(**overrides: object) -> dict:
    request = _read_request(**overrides).to_dict()
    return {
        "read_view_schema": READ_VIEW_SCHEMA,
        "read_request": request,
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


class MeasurementRecordReadViewPrototypeTest(unittest.TestCase):
    def test_reads_primary_table_through_writer_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)

            run = read_created_record_primary_table(
                _read_source(),
                storage_root=storage_root,
            )
            creation_manifest = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "primary_table_ready")
        self.assertEqual(run.table["row_count"], 5)
        self.assertEqual(run.table["declared_row_count"], 5)
        self.assertEqual(
            set(run.table),
            {
                "table_schema",
                "source",
                "format",
                "classification",
                "columns",
                "row_count",
                "declared_row_count",
                "rows",
                "preview",
            },
        )
        self.assertEqual(
            [column["name"] for column in run.table["columns"]],
            ["drive_amplitude", "excited_state_probability"],
        )
        self.assertEqual(len(run.table["preview"]["rows"]), 2)
        self.assertEqual(run.table["preview"]["rows"][0]["drive_amplitude"], "0.00")
        self.assertEqual(creation_manifest["primary_data"]["state"], "not_recorded")

        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "artifact_posture",
                "classification",
                "request",
                "record_manifest",
                "writer_receipt",
                "table",
                "review_findings",
            },
        )
        self.assertEqual(summary["artifact_posture"], "local_record_read_view")
        self.assertEqual(summary["classification"], "primary_table_ready")
        self.assertEqual(
            summary["writer_receipt"]["primary_data_path"],
            "records/run-3101-rabi/primary.csv",
        )

    def test_requires_writer_receipt_record_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["record"]["record_id"] = "other-record"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record_id"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_primary_data_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            primary_path.write_text("drive_amplitude,excited_state_probability\n0.0,broken\n")

            with self.assertRaisesRegex(ValueError, "digest"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_missing_writer_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            (storage_root / "records" / "run-3101-rabi" / "writer-receipt.json").unlink()

            with self.assertRaisesRegex(ValueError, "writer receipt"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_writer_receipt_row_count_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["primary_data"]["rows_recorded"] = 4
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            run = read_created_record_primary_table_from_request(
                _read_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "primary_table_review_needed")
        self.assertEqual(
            [finding["code"] for finding in run.review_findings],
            ["primary_table_row_count_mismatch"],
        )

    def test_malformed_primary_csv_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            content = b"drive_amplitude,excited_state_probability\n0.0,0.1,extra\n"
            primary_path.write_bytes(content)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["primary_data"]["digest"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
            receipt["primary_data"]["size_bytes"] = len(content)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "rows must match"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_symlink_primary_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            primary_path.unlink()
            primary_path.symlink_to(Path(temp_dir) / "external-primary.csv")

            with self.assertRaisesRegex(ValueError, "primary data must not be a symlink"):
                read_created_record_primary_table_from_request(
                    _read_request(),
                    storage_root=storage_root,
                )

    def test_read_request_writer_receipt_must_stay_under_record_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "writer_receipt_path"):
            _read_request(writer_receipt_path="outside/writer-receipt.json")


if __name__ == "__main__":
    unittest.main()
