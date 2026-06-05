from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)
from scopecat.measurement_records.read_model_refresh import (
    MeasurementRecordReadModelRefreshRequest,
    refresh_measurement_record_read_model_from_read_view,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_SCHEMA
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    read_created_record_primary_table_from_request,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "measurement_records"
    / "normalized_primary_table"
    / "basic_table"
    / "source"
    / "primary.csv"
)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_request() -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id="read-primary-run-3101-rabi",
        record_id="run-3101-rabi",
        record_dir="records/run-3101-rabi",
        writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
        preview_row_limit=2,
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


def _populate_record(storage_root: Path, content_root: Path) -> None:
    source_path = content_root / "source" / "primary.csv"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(SOURCE_FIXTURE.read_bytes())
    run = import_measurement_record_from_request(
        MeasurementRecordDurableImportRequest(
            request_id="import-run-3101-rabi",
            approval_state="approved",
            record_id="run-3101-rabi",
            record_dir="records/run-3101-rabi",
            primary_data_path="records/run-3101-rabi/primary.csv",
            writer_receipt_path="records/run-3101-rabi/writer-receipt.json",
            finalization_receipt_path="records/run-3101-rabi/finalization-receipt.json",
            read_model_path="records/run-3101-rabi/record-read-model.json",
            import_source=MeasurementRecordImportSource(
                source_kind="fixture_normalized_primary_data",
                source_id="refresh-fixture",
                source_item_id="refresh-primary",
                content_ref="source/primary.csv",
                declared_digest=_digest(source_path),
                size_bytes=source_path.stat().st_size,
                rows_recorded=5,
            ),
        ),
        content_root=content_root,
        storage_root=storage_root,
    )
    if not run.imported:
        raise AssertionError(run.to_dict())
    (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").unlink()


def _read_view(storage_root: Path):
    return read_created_record_primary_table_from_request(
        _read_request(),
        storage_root=storage_root,
    )


def _write_existing_read_model(storage_root: Path) -> None:
    run = refresh_measurement_record_read_model_from_read_view(
        _refresh_request(request_id="existing-read-model-run-3101-rabi"),
        read_view=_read_view(storage_root),
        storage_root=storage_root,
    )
    if not run.refreshed:
        raise AssertionError(run.to_dict())


class MeasurementRecordReadModelRefreshPrototypeTest(unittest.TestCase):
    def test_refresh_creates_missing_read_model_by_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
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
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            _write_existing_read_model(storage_root)
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
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            _write_existing_read_model(storage_root)
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
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            _write_existing_read_model(storage_root)

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
            content_root.mkdir()
            _populate_record(storage_root, content_root)

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
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            _write_existing_read_model(storage_root)
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
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            _write_existing_read_model(storage_root)
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

    def test_refreshed_model_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            content_root = Path(temp_dir) / "content"
            storage_root.mkdir()
            content_root.mkdir()
            _populate_record(storage_root, content_root)
            refresh_measurement_record_read_model_from_read_view(
                _refresh_request(),
                read_view=_read_view(storage_root),
                storage_root=storage_root,
            )

            read_model = json.loads(
                (storage_root / "records" / "run-3101-rabi" / "record-read-model.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(read_model["schema"], READ_MODEL_SCHEMA)
        self.assertEqual(read_model["record"]["record_id"], "run-3101-rabi")
        self.assertEqual(read_model["primary_data"]["observed_row_count"], 5)

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
