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


def _creation_request(*, state: str = "created") -> MeasurementRecordCreationRequest:
    return MeasurementRecordCreationRequest(
        request_id="create-record-run-3101-rabi",
        approval_state="approved",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        initial_lifecycle_state=state,
        creation_source_kind="writer",
        label="Stored Rabi run 3101",
        experiment_type="rabi_amplitude",
    )


def _writer_request(**overrides: object) -> MeasurementRecordWriterRequest:
    values = {
        "request_id": "write-primary-run-3101-rabi",
        "approval_state": "approved",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "primary_data_path": "records/run-3101-rabi/primary.csv",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "primary_data_format": "csv_table",
        "expected_rows": 5,
        "chunks": (_chunk_one(), _chunk_two()),
    }
    values.update(overrides)
    return MeasurementRecordWriterRequest(**values)


def _writer_source(**overrides: object) -> dict:
    request = _writer_request(**overrides).to_dict()
    return {
        "writer_request": request,
    }


def _create_shell(storage_root: Path, *, state: str = "created") -> None:
    run = create_measurement_record_from_request(
        _creation_request(state=state),
        storage_root=storage_root,
    )
    if not run.created:
        raise AssertionError(run.to_dict())


class MeasurementRecordWriterIntegrationPrototypeTest(unittest.TestCase):
    def test_writes_primary_data_and_writer_receipt_to_created_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)

            run = write_created_record_primary_data_from_request(
                _writer_request(),
                storage_root=storage_root,
                content_root=content_root,
            )
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            receipt_path = storage_root / "records" / "run-3101-rabi" / "writer-receipt.json"
            primary_text = primary_path.read_text(encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            creation_manifest = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "written_to_created_record")
        self.assertTrue(run.written)
        self.assertEqual(
            primary_text,
            (CHUNK_FIXTURE / "chunks" / "chunk-1.csv").read_text(encoding="utf-8")
            + (CHUNK_FIXTURE / "chunks" / "chunk-2.csv").read_text(encoding="utf-8"),
        )
        self.assertEqual(receipt["schema"], "measurement_record_writer_receipt_v0")
        self.assertEqual(receipt["record"]["record_id"], "run-3101-rabi")
        self.assertEqual(receipt["primary_data"]["rows_recorded"], 5)
        self.assertEqual(
            set(receipt),
            {"schema", "record", "writer_request", "primary_data", "chunks"},
        )
        self.assertEqual(creation_manifest["primary_data"]["state"], "not_recorded")
        self.assertEqual(
            [item["kind"] for item in run.write_results],
            ["primary_data", "writer_receipt"],
        )
        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "artifact_posture",
                "classification",
                "request",
                "record_manifest",
                "writer_integration",
            },
        )
        self.assertEqual(summary["classification"], "written_to_created_record")

    def test_unapproved_writer_request_does_not_mutate_created_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)

            run = write_created_record_primary_data_from_request(
                _writer_request(approval_state="needs_review"),
                storage_root=storage_root,
                content_root=content_root,
            )

            record_dir = storage_root / "records" / "run-3101-rabi"
            self.assertFalse((record_dir / "primary.csv").exists())
            self.assertFalse((record_dir / "writer-receipt.json").exists())

        self.assertEqual(run.classification, "blocked_before_writer_integration")
        self.assertFalse(run.written)

    def test_requires_matching_creation_manifest_record_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)
            manifest_path = storage_root / "records" / "run-3101-rabi" / "record-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["record"]["record_id"] = "other-record"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record_id"):
                write_created_record_primary_data_from_request(
                    _writer_request(),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse((storage_root / "records" / "run-3101-rabi" / "primary.csv").exists())

    def test_review_needed_creation_manifest_blocks_writer_integration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root, state="review_needed")

            with self.assertRaisesRegex(ValueError, "lifecycle_state"):
                write_created_record_primary_data_from_request(
                    _writer_request(),
                    storage_root=storage_root,
                    content_root=content_root,
                )

    def test_existing_primary_data_target_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)
            primary_path = storage_root / "records" / "run-3101-rabi" / "primary.csv"
            primary_path.write_text("already here", encoding="utf-8")

            run = write_created_record_primary_data_from_request(
                _writer_request(),
                storage_root=storage_root,
                content_root=content_root,
            )

            self.assertEqual(primary_path.read_text(encoding="utf-8"), "already here")
            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "writer-receipt.json").exists()
            )

        self.assertEqual(run.classification, "blocked_before_writer_integration")
        self.assertIn("target already exists", run.write_error or "")

    def test_chunk_digest_mismatch_is_rejected_before_mutation(self) -> None:
        bad_chunk = MeasurementRecordWriterChunk(
            chunk_id="chunk-3101-1",
            sequence=1,
            event_id="evt-3101-data-1",
            content_ref="chunks/chunk-1.csv",
            declared_digest="sha256:" + "a" * 64,
            size_bytes=(CHUNK_FIXTURE / "chunks" / "chunk-1.csv").stat().st_size,
            rows_recorded=5,
            total_rows_recorded=5,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)

            with self.assertRaisesRegex(ValueError, "digest"):
                write_created_record_primary_data_from_request(
                    _writer_request(chunks=(bad_chunk,), expected_rows=5),
                    storage_root=storage_root,
                    content_root=content_root,
                )

            self.assertFalse((storage_root / "records" / "run-3101-rabi" / "primary.csv").exists())

    def test_writer_receipt_failure_rolls_back_primary_data(self) -> None:
        def fail_second_write(path: Path, content: bytes) -> None:
            if path.name == "writer-receipt.json":
                raise OSError("simulated receipt failure")
            path.write_bytes(content)

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _create_shell(storage_root)

            run = write_created_record_primary_data_from_request(
                _writer_request(),
                storage_root=storage_root,
                content_root=content_root,
                file_writer=fail_second_write,
            )

            record_dir = storage_root / "records" / "run-3101-rabi"
            self.assertFalse((record_dir / "primary.csv").exists())
            self.assertFalse((record_dir / "writer-receipt.json").exists())

        self.assertEqual(run.classification, "rolled_back_after_writer_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("simulated receipt failure", run.write_error or "")

    def test_writer_output_paths_must_stay_under_record_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "primary_data_path"):
            _writer_request(primary_data_path="outside/primary.csv")

    def test_writer_output_paths_must_not_overlap(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            _writer_request(writer_receipt_path="records/run-3101-rabi/primary.csv/meta.json")


if __name__ == "__main__":
    unittest.main()
