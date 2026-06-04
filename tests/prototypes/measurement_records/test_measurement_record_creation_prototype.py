from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records import (
    MeasurementRecordCreationRequest,
    create_measurement_record,
    create_measurement_record_from_request,
)
from scopecat.measurement_records.creation import CREATION_SCHEMA


def _request_source(**overrides: object) -> dict:
    request = {
        "request_id": "create-record-rabi-001",
        "approval_state": "approved",
        "record_id": "rabi-001",
        "record_dir": "records/rabi-001",
        "initial_lifecycle_state": "created",
        "creation_source_kind": "manual",
        "created_at": "2026-05-29T10:15:00Z",
        "label": "Rabi 001",
        "experiment_type": "rabi",
    }
    request.update(overrides)
    return {
        "creation_schema": CREATION_SCHEMA,
        "creation_request": request,
    }


class MeasurementRecordCreationPrototypeTest(unittest.TestCase):
    def test_approved_creation_writes_initial_record_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = create_measurement_record(_request_source(), storage_root=storage_root)
            manifest_path = storage_root / "records" / "rabi-001" / "record-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(run.classification, "created_record")
        self.assertTrue(run.created)
        self.assertEqual(
            run.created_paths,
            ("records", "records/rabi-001", "records/rabi-001/record-manifest.json"),
        )
        self.assertEqual(manifest["schema"], "measurement_record_creation_v0")
        self.assertEqual(manifest["record"]["record_id"], "rabi-001")
        self.assertEqual(manifest["record"]["lifecycle_state"], "created")
        self.assertEqual(manifest["record"]["created_at"], "2026-05-29T10:15:00Z")
        self.assertEqual(manifest["creation"]["source_kind"], "manual")
        self.assertEqual(manifest["primary_data"], {"state": "not_recorded", "references": []})
        self.assertEqual(
            set(manifest),
            {"schema", "record", "creation", "storage", "primary_data"},
        )

        receipt = run.to_dict()
        self.assertEqual(
            set(receipt),
            {"artifact_posture", "classification", "request", "creation"},
        )
        self.assertEqual(receipt["artifact_posture"], "local_record_creation_receipt")
        self.assertEqual(receipt["classification"], "created_record")
        self.assertEqual(receipt["creation"]["record_id"], "rabi-001")
        self.assertEqual(
            receipt["creation"]["manifest_path"], "records/rabi-001/record-manifest.json"
        )

    def test_unapproved_creation_does_not_mutate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = create_measurement_record(
                _request_source(approval_state="needs_review"),
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_creation")
        self.assertFalse(run.created)
        self.assertIsNone(run.creation_error)

    def test_existing_record_directory_blocks_creation_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            record_dir = storage_root / "records" / "rabi-001"
            record_dir.mkdir(parents=True)

            run = create_measurement_record(_request_source(), storage_root=storage_root)

            self.assertFalse((record_dir / "record-manifest.json").exists())

        self.assertEqual(run.classification, "blocked_before_creation")
        self.assertFalse(run.created)
        self.assertIn("target already exists", run.creation_error or "")

    def test_invalid_record_id_is_rejected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "record_id"):
                create_measurement_record(
                    _request_source(record_id="../private"),
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records").exists())

    def test_invalid_record_directory_is_rejected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "record_dir"):
                create_measurement_record(
                    _request_source(record_dir="../records/rabi-001"),
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records").exists())

    def test_symlink_parent_is_rejected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            external = Path(temp_dir) / "external"
            external.mkdir()
            (storage_root / "records").symlink_to(external)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                create_measurement_record(_request_source(), storage_root=storage_root)

            self.assertEqual(list(external.iterdir()), [])

    def test_manifest_write_failure_rolls_back_created_directories(self) -> None:
        def fail_manifest_write(_path: Path, _content: dict) -> None:
            raise OSError("simulated manifest failure")

        request = MeasurementRecordCreationRequest(
            request_id="create-record-rabi-001",
            approval_state="approved",
            record_id="rabi-001",
            record_dir="records/rabi-001",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = create_measurement_record_from_request(
                request,
                storage_root=storage_root,
                manifest_writer=fail_manifest_write,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "rolled_back_after_creation_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("simulated manifest failure", run.creation_error or "")

    def test_typed_request_supports_in_progress_initial_state(self) -> None:
        request = MeasurementRecordCreationRequest(
            request_id="create-record-rabi-002",
            approval_state="approved",
            record_id="rabi-002",
            record_dir="records/rabi-002",
            initial_lifecycle_state="in_progress",
            creation_source_kind="writer",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = create_measurement_record_from_request(request, storage_root=storage_root)
            manifest = json.loads(
                (storage_root / "records" / "rabi-002" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "created_record")
        self.assertEqual(manifest["record"]["lifecycle_state"], "in_progress")
        self.assertEqual(manifest["creation"]["source_kind"], "writer")
