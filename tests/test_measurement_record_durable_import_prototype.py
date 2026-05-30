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
    import_measurement_record,
    import_measurement_record_from_request,
)
from scopecat.measurement_records.durable_import import (
    DURABLE_IMPORT_POLICY,
    DURABLE_IMPORT_SCHEMA,
)

ROOT = Path(__file__).resolve().parents[1]
CHUNK_FIXTURE = ROOT / "tests" / "fixtures" / "measurement_storage_writer" / "basic_append"


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


def _raw_source(**overrides: object) -> dict:
    return {
        "durable_import_schema": DURABLE_IMPORT_SCHEMA,
        "durable_import_policy": DURABLE_IMPORT_POLICY,
        "durable_import_request": _request(**overrides).to_dict(),
    }


class MeasurementRecordDurableImportPrototypeTest(unittest.TestCase):
    def test_approved_import_creates_new_record_pipeline_outputs(self) -> None:
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
        self.assertEqual(run.to_dict()["pipeline"]["projection"], "projected_read_model")
        self.assertIn("manifest_replacement", run.to_dict()["workflow"]["does_not_claim"])

    def test_raw_source_import_uses_candidate_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            run = import_measurement_record(
                _raw_source(),
                content_root=content_root,
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "imported_new_record")

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
        self.assertIn("creation", run.import_error or "")

    def test_row_count_mismatch_rolls_back_new_record(self) -> None:
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

        self.assertEqual(run.classification, "rolled_back_after_import_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("finalization", run.import_error or "")

    def test_read_view_failure_after_write_rolls_back_and_returns_receipt(self) -> None:
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

        self.assertEqual(run.classification, "rolled_back_after_import_failure")
        self.assertTrue(run.rollback_performed)
        self.assertFalse(run.partial_commit)
        self.assertIn("read_view", run.import_error or "")
        self.assertIn("rows must match", run.import_error or "")

    def test_projection_failure_rolls_back_new_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")

            def failing_projection_writer(path: Path, content: bytes) -> None:
                path.write_bytes(content)
                raise RuntimeError("simulated projection failure")

            run = import_measurement_record_from_request(
                _request(),
                content_root=content_root,
                storage_root=storage_root,
                projection_model_writer=failing_projection_writer,
            )

            self.assertFalse((storage_root / "records" / "run-3101-rabi").exists())

        self.assertEqual(run.classification, "rolled_back_after_import_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("projection", run.import_error or "")

    def test_source_policy_must_match_candidate_boundary(self) -> None:
        source = _raw_source()
        source["durable_import_policy"] = {
            **DURABLE_IMPORT_POLICY,
            "record_manifest": "replaced",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()

            with self.assertRaisesRegex(ValueError, "policy"):
                import_measurement_record(
                    source,
                    content_root=content_root,
                    storage_root=storage_root,
                )


if __name__ == "__main__":
    unittest.main()
