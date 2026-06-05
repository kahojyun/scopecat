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
from scopecat.measurement_records.read_model_refresh import (
    MeasurementRecordReadModelRefreshRequest,
    refresh_measurement_record_read_model_from_read_view,
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


def _projection_request() -> MeasurementRecordReadModelProjectionRequest:
    return MeasurementRecordReadModelProjectionRequest(
        request_id="project-read-model-run-3101-rabi",
        approval_state="approved",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
        finalization_receipt_path="records/run-3101-rabi/finalization-receipt.json",
        read_model_path="records/run-3101-rabi/record-read-model.json",
    )


def _refresh_request(**overrides: object) -> MeasurementRecordReadModelRefreshRequest:
    values = {
        "request_id": "refresh-read-model-run-3101-rabi",
        "approval_state": "approved",
        "record_id": "run-3101-rabi",
        "record_dir": "records/run-3101-rabi",
        "writer_receipt_path": "records/run-3101-rabi/writer-receipt.json",
        "finalization_receipt_path": "records/run-3101-rabi/finalization-receipt.json",
        "read_model_path": "records/run-3101-rabi/record-read-model.json",
        "expected_target_condition": "missing",
    }
    values.update(overrides)
    return MeasurementRecordReadModelRefreshRequest(**values)


def _refresh_source(**overrides: object) -> dict:
    return {
        "refresh_request": _refresh_request(**overrides).to_dict(),
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


def _finalize(storage_root: Path) -> None:
    run = finalize_measurement_record_from_read_view(
        _finalization_request(),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not run.finalized:
        raise AssertionError(run.to_dict())


def _project(storage_root: Path) -> None:
    run = project_measurement_record_read_model_from_read_view(
        _projection_request(),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not run.projected:
        raise AssertionError(run.to_dict())


class MeasurementRecordReadModelRefreshPrototypeTest(unittest.TestCase):
    def test_refresh_creates_missing_read_model_by_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            manifest_path = storage_root / "records" / "run-3101-rabi" / "record-manifest.json"
            manifest_before = manifest_path.read_text(encoding="utf-8")

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))
            manifest_after = manifest_path.read_text(encoding="utf-8")
            temp_path = (
                storage_root
                / "records"
                / "run-3101-rabi"
                / "record-read-model.refresh-refresh-read-model-run-3101-rabi.tmp"
            )

        self.assertEqual(run.classification, "refreshed_read_model")
        self.assertTrue(run.refreshed)
        self.assertTrue(run.replacement_performed)
        self.assertFalse(temp_path.exists())
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
                "refresh",
            },
        )
        self.assertEqual(
            read_model["refresh"]["previous_read_model_authority"], "overwrite_guard_only"
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
                "refresh",
            },
        )
        self.assertEqual(summary["classification"], "refreshed_read_model")

    def test_refresh_replaces_existing_read_model_when_digest_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            _project(storage_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            previous_digest = _digest(read_model_path)

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(
                    expected_target_condition="replace_existing",
                    expected_current_read_model_digest=previous_digest,
                ),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )
            read_model = json.loads(read_model_path.read_text(encoding="utf-8"))

        self.assertEqual(run.classification, "refreshed_read_model")
        self.assertEqual(run.previous_read_model_digest, previous_digest)
        self.assertNotEqual(run.refreshed_read_model_digest, previous_digest)
        self.assertEqual(read_model["refresh"]["request_id"], "refresh-read-model-run-3101-rabi")

    def test_replace_existing_blocks_when_digest_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            _project(storage_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            previous = read_model_path.read_text(encoding="utf-8")

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(
                    expected_target_condition="replace_existing",
                    expected_current_read_model_digest="sha256:" + "0" * 64,
                ),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )
            read_model_after = read_model_path.read_text(encoding="utf-8")

        self.assertEqual(run.classification, "blocked_before_refresh")
        self.assertFalse(run.replacement_performed)
        self.assertEqual(read_model_after, previous)
        self.assertIn("digest does not match", run.refresh_error or "")

    def test_missing_condition_blocks_when_target_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            _project(storage_root)

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "blocked_before_refresh")
        self.assertIn("already exists", run.refresh_error or "")

    def test_unapproved_refresh_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(approval_state="needs_review"),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

            self.assertFalse(
                (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").exists()
            )

        self.assertEqual(run.classification, "blocked_before_refresh")
        self.assertFalse(run.refreshed)

    def test_write_failure_cleans_temp_and_leaves_existing_read_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            _project(storage_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            previous = read_model_path.read_text(encoding="utf-8")
            previous_digest = _digest(read_model_path)
            temp_path = (
                storage_root
                / "records"
                / "run-3101-rabi"
                / "record-read-model.refresh-refresh-read-model-run-3101-rabi.tmp"
            )

            def failing_writer(path: Path, content: bytes) -> None:
                path.write_bytes(content)
                raise RuntimeError("simulated refresh write failure")

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(
                    expected_target_condition="replace_existing",
                    expected_current_read_model_digest=previous_digest,
                ),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
                model_writer=failing_writer,
            )
            read_model_after = read_model_path.read_text(encoding="utf-8")

        self.assertEqual(run.classification, "blocked_before_refresh")
        self.assertTrue(run.cleanup_performed)
        self.assertFalse(temp_path.exists())
        self.assertEqual(read_model_after, previous)

    def test_replace_failure_after_replace_reports_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            _project(storage_root)
            read_model_path = storage_root / "records" / "run-3101-rabi" / "record-read-model.json"
            previous_digest = _digest(read_model_path)
            previous = read_model_path.read_text(encoding="utf-8")

            def replacing_then_failing(temp: Path, target: Path) -> None:
                temp.replace(target)
                raise RuntimeError("simulated post-replace failure")

            run = refresh_measurement_record_read_model_from_read_view(
                _refresh_request(
                    expected_target_condition="replace_existing",
                    expected_current_read_model_digest=previous_digest,
                ),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
                model_replacer=replacing_then_failing,
            )
            read_model_after = read_model_path.read_text(encoding="utf-8")

        self.assertEqual(run.classification, "refresh_replaced_with_error")
        self.assertTrue(run.replacement_performed)
        self.assertFalse(run.cleanup_performed)
        self.assertNotEqual(read_model_after, previous)

    def test_refreshed_model_remains_catalog_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            shutil.copytree(CHUNK_FIXTURE / "chunks", content_root / "chunks")
            _populate_record(storage_root, content_root)
            _finalize(storage_root)
            refresh_measurement_record_read_model_from_read_view(
                _refresh_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

            catalog = catalog_measurement_record_read_models_from_request(
                MeasurementRecordCatalogRequest(
                    request_id="catalog-after-refresh",
                    records_dir="records",
                    verify_source_digests=True,
                ),
                storage_root=storage_root,
            )

        self.assertEqual(catalog.classification, "read_model_catalog_ready")
        self.assertEqual(len(catalog.entries), 1)

    def test_replace_existing_requires_expected_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected_current_read_model_digest"):
            _refresh_request(expected_target_condition="replace_existing")

    def test_read_model_path_must_be_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical"):
            _refresh_request(read_model_path="records/run-3101-rabi/custom-read-model.json")

    def test_refresh_paths_reject_parent_child_overlap(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            _refresh_request(
                finalization_receipt_path=(
                    "records/run-3101-rabi/record-read-model.json/finalization-receipt.json"
                )
            )


if __name__ == "__main__":
    unittest.main()
