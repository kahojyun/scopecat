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
from scopecat.measurement_records.finalization import (
    MeasurementRecordFinalizationRequest,
    finalize_measurement_record_from_read_view,
)
from scopecat.measurement_records.read_model_catalog import (
    MeasurementRecordCatalogRequest,
    catalog_measurement_record_read_models_from_request,
)
from scopecat.measurement_records.read_model_projection import (
    MeasurementRecordReadModelProjectionRequest,
    project_measurement_record_read_model_from_read_view,
)
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    read_created_record_primary_table_from_request,
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


def _read_request() -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id="read-primary-run-3101-rabi",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
        preview_row_limit=2,
    )


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


def _catalog_request(**overrides: object) -> MeasurementRecordCatalogRequest:
    values = {
        "request_id": "catalog-projected-records",
        "records_dir": "records",
        "verify_source_digests": True,
    }
    values.update(overrides)
    return MeasurementRecordCatalogRequest(**values)


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


def _populate_projected_record(storage_root: Path, content_root: Path) -> None:
    _populate_record(storage_root, content_root)
    finalize_run = finalize_measurement_record_from_read_view(
        _finalization_request(),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not finalize_run.finalized:
        raise AssertionError(finalize_run.to_dict())
    projection_run = project_measurement_record_read_model_from_read_view(
        _projection_request(),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not projection_run.projected:
        raise AssertionError(projection_run.to_dict())


class MeasurementRecordReadModelCatalogPrototypeTest(unittest.TestCase):
    def test_catalog_lists_projected_read_model_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model_before = read_model_path.read_text(encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )
            read_model_after = read_model_path.read_text(encoding="utf-8")

        self.assertEqual(run.classification, "read_model_catalog_ready")
        self.assertEqual(len(run.entries), 1)
        self.assertEqual(run.entries[0]["record_id"], "run-3101-rabi")
        self.assertEqual(run.entries[0]["lifecycle_state"], "complete")
        self.assertEqual(run.entries[0]["primary_data"]["observed_row_count"], 5)
        self.assertEqual(run.entries[0]["table"]["preview_row_count"], 2)
        self.assertEqual(run.review_findings, ())
        self.assertEqual(read_model_after, read_model_before)
        summary = run.to_dict()
        self.assertEqual(
            set(summary),
            {
                "artifact_posture",
                "classification",
                "request",
                "storage_root",
                "entries",
                "review_findings",
            },
        )
        self.assertEqual(summary["classification"], "read_model_catalog_ready")

    def test_missing_read_model_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_review_needed")
        self.assertEqual(run.entries, ())
        self.assertEqual(run.review_findings[0]["code"], "read_model_missing")

    def test_malformed_read_model_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            record_dir = storage_root / "records" / "bad-record"
            record_dir.mkdir(parents=True)
            (record_dir / "record-read-model.json").write_text("{not json", encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_review_needed")
        self.assertEqual(run.entries, ())
        self.assertEqual(run.review_findings[0]["code"], "read_model_invalid")

    def test_conflicting_read_model_path_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            read_model["projection"]["read_model_path"] = "records/other/record-read-model.json"
            read_model_path.write_text(json.dumps(read_model), encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_review_needed")
        self.assertEqual(run.entries, ())
        self.assertEqual(run.review_findings[0]["code"], "read_model_invalid")
        self.assertIn("path conflicts", run.review_findings[0]["message"])

    def test_source_digest_mismatch_is_review_finding_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "finalization-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["finalization"]["operator_reason"] = "changed after projection"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_review_needed")
        self.assertEqual(len(run.entries), 1)
        self.assertEqual(run.review_findings[0]["code"], "read_model_source_digest_mismatch")
        self.assertEqual(
            set(run.review_findings[0]),
            {"code", "severity", "target", "message"},
        )

    def test_source_digest_verification_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            content_root = temp_root / "content"
            external_root = temp_root / "external-sources"
            storage_root.mkdir()
            external_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            record_dir = storage_root / "records" / "run-3101-rabi"
            read_model_path = record_dir / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            external_manifest = external_root / "record-manifest.json"
            external_manifest.write_bytes((record_dir / "record-manifest.json").read_bytes())
            (record_dir / "linked-sources").symlink_to(external_root, target_is_directory=True)
            read_model["sources"]["creation_manifest"]["path"] = (
                "records/run-3101-rabi/linked-sources/record-manifest.json"
            )
            read_model["sources"]["creation_manifest"]["digest"] = _digest(external_manifest)
            read_model_path.write_text(json.dumps(read_model), encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_review_needed")
        self.assertEqual(len(run.entries), 1)
        self.assertEqual(run.review_findings[0]["code"], "read_model_source_symlink_parent")

    def test_source_digest_verification_can_be_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_projected_record(storage_root, content_root)
            receipt_path = storage_root / "records" / "run-3101-rabi" / "finalization-receipt.json"
            receipt_path.write_text("changed after projection", encoding="utf-8")

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(verify_source_digests=False),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_ready")
        self.assertEqual(len(run.entries), 1)
        self.assertEqual(run.review_findings, ())

    def test_missing_records_dir_is_empty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = catalog_measurement_record_read_models_from_request(
                _catalog_request(),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "read_model_catalog_ready")
        self.assertEqual(run.entries, ())
        self.assertEqual(run.review_findings, ())


if __name__ == "__main__":
    unittest.main()
