from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
CHUNK_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "durable_import"
    / "basic_append"
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _digest_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _source(**overrides: object) -> MeasurementRecordImportSource:
    path = CHUNK_FIXTURE / "chunks" / "chunk-1.csv"
    values = {
        "source_kind": "adapter_normalized_primary_data",
        "source_id": "adapter-output-3101",
        "source_item_id": "primary-3101-rabi",
        "content_ref": "chunks/chunk-1.csv",
        "declared_digest": _digest(path),
        "size_bytes": path.stat().st_size,
        "rows_recorded": 3,
        "primary_data_format": "csv_table",
    }
    values.update(overrides)
    return MeasurementRecordImportSource(**values)


def _request(**overrides: object) -> MeasurementRecordDurableImportRequest:
    values = {
        "request_id": "import-run-3101-rabi",
        "approval_state": "approved",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "primary_data_path": "records/run-3101-rabi/primary.csv",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "finalization_receipt_path": "records/run-3101-rabi/finalization-receipt.json",
        "read_model_path": "records/run-3101-rabi/record-read-model.json",
        "import_source": _source(),
        "creation_source_kind": "import",
        "label": "Imported Rabi run",
        "experiment_type": "rabi",
    }
    values.update(overrides)
    return MeasurementRecordDurableImportRequest(**values)


class MeasurementRecordDurableImportPrototypeTest(unittest.TestCase):
    def test_approved_import_creates_new_record_storage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            run = import_measurement_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
            )
            record_dir = storage_root / "records" / "run-3101-rabi"
            manifest = json.loads((record_dir / "record-manifest.json").read_text())
            read_model = json.loads((record_dir / "record-read-model.json").read_text())

        self.assertEqual(run.classification, "imported_new_record")
        self.assertTrue(run.imported)
        self.assertEqual(manifest["creation"]["source_kind"], "import")
        self.assertEqual(manifest["record"]["label"], "Imported Rabi run")
        self.assertEqual(read_model["record"]["lifecycle_state"], "complete")
        self.assertEqual(read_model["primary_data"]["observed_row_count"], 3)
        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "classification",
                "request",
                "storage_root",
                "content_root",
                "import_result",
                "stored_record",
            },
        )
        self.assertEqual(summary["classification"], "imported_new_record")
        self.assertEqual(
            summary["stored_record"]["read_model_path"],
            "records/run-3101-rabi/record-read-model.json",
        )

    def test_unapproved_import_does_not_mutate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            run = import_measurement_record_from_request(
                _request(approval_state="needs_review"),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_import")
        self.assertFalse(run.imported)

    def test_source_digest_mismatch_blocks_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            run = import_measurement_record_from_request(
                _request(import_source=_source(declared_digest="sha256:" + "0" * 64)),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_import")
        self.assertIn("digest does not match", run.import_error or "")

    def test_preexisting_destination_blocks_via_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            existing = storage_root / "records" / "run-3101-rabi"
            existing.mkdir(parents=True)

            run = import_measurement_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertTrue(existing.exists())
            self.assertEqual(list(existing.iterdir()), [])

        self.assertEqual(run.classification, "blocked_before_import")
        self.assertIn("record_dir target already exists", run.import_error or "")

    def test_row_count_mismatch_blocks_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            run = import_measurement_record_from_request(
                _request(import_source=_source(rows_recorded=2)),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records" / "run-3101-rabi").exists())
            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_import")
        self.assertFalse(run.rollback_performed)
        self.assertIn("row count does not match", run.import_error or "")

    def test_malformed_source_blocks_before_mutation(self) -> None:
        malformed_csv = b"time,signal\n0\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            source_dir = content_root / "chunks"
            source_dir.mkdir(parents=True)
            (source_dir / "malformed.csv").write_bytes(malformed_csv)

            run = import_measurement_record_from_request(
                _request(
                    import_source=_source(
                        content_ref="chunks/malformed.csv",
                        declared_digest=_digest_bytes(malformed_csv),
                        size_bytes=len(malformed_csv),
                        rows_recorded=1,
                    )
                ),
                content_root=content_root,
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records" / "run-3101-rabi").exists())
            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_import")
        self.assertFalse(run.rollback_performed)
        self.assertFalse(run.partial_commit)
        self.assertIn("rows must match", run.import_error or "")

    def test_read_model_write_failure_rolls_back_new_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            def failing_read_model_writer(path: Path, content: bytes) -> None:
                path.write_bytes(content)
                raise RuntimeError("simulated read model failure")

            run = import_measurement_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
                read_model_writer=failing_read_model_writer,
            )

            self.assertFalse((storage_root / "records" / "run-3101-rabi").exists())

        self.assertEqual(run.classification, "rolled_back_after_import_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("read model write failed", run.import_error or "")

    def test_read_model_path_must_be_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical"):
            _request(read_model_path="records/run-3101-rabi/custom-read-model.json")


if __name__ == "__main__":
    unittest.main()
