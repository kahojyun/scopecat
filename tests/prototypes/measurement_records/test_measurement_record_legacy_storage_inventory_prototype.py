from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scopecat.measurement_records.creation import (
    MeasurementRecordCreationRequest,
    create_measurement_record_from_request,
)
from scopecat.measurement_records.legacy_run import (
    LEGACY_RUN_RECEIPT_SCHEMA,
    LegacyRunLocator,
    LegacyRunRecordRequest,
    record_legacy_measurement_run_from_request,
)
from scopecat.measurement_records.storage_inventory import (
    MeasurementRecordStorageInventoryRequest,
    list_measurement_record_storage_from_request,
)


def _legacy_request(**overrides: object) -> LegacyRunRecordRequest:
    values = {
        "request_id": "record-legacy-run-001",
        "approval_state": "approved",
        "record_id": "legacy-run-001",
        "record_dir": "records/legacy-run-001",
        "legacy_system_id": "legacy-labview",
        "legacy_run_id": "lv-run-001",
        "created_at": "2026-05-31T09:15:00Z",
        "label": "Legacy Run 001",
        "experiment_type": "legacy-rabi",
        "run_started_at": "2026-05-31T09:00:00Z",
        "run_completed_at": "2026-05-31T09:10:00Z",
        "locators": (
            LegacyRunLocator(
                locator_id="legacy-primary-csv",
                kind="workspace_relative_path",
                role="primary_data",
                value="legacy/runs/lv-run-001/primary.csv",
            ),
            LegacyRunLocator(
                locator_id="legacy-debug-log",
                kind="workspace_relative_path",
                role="debug_log",
                value="legacy/runs/lv-run-001/debug.log",
                state="unavailable",
                reason="not copied into this workspace",
            ),
        ),
    }
    values.update(overrides)
    return LegacyRunRecordRequest(**values)


def _legacy_source(**overrides: object) -> dict:
    return {
        "legacy_run_record_request": _legacy_request(**overrides).to_dict(),
    }


def _inventory_source(**overrides: object) -> dict:
    request = {
        "request_id": "inventory-records",
        "records_dir": "records",
        "include_read_models": True,
        "include_legacy_receipts": True,
    }
    request.update(overrides)
    return {
        "storage_inventory_request": request,
    }


def _inventory_request(**overrides: object) -> MeasurementRecordStorageInventoryRequest:
    request = {
        "request_id": "inventory-records",
        "records_dir": "records",
        "include_read_models": True,
        "include_legacy_receipts": True,
    }
    request.update(overrides)
    return MeasurementRecordStorageInventoryRequest(**request)


def _write_minimal_projected_record(storage_root: Path) -> None:
    create_run = create_measurement_record_from_request(
        MeasurementRecordCreationRequest(
            request_id="create-projected-run-001",
            approval_state="approved",
            record_id="projected-run-001",
            record_dir="records/projected-run-001",
            initial_lifecycle_state="created",
            creation_source_kind="writer",
            label="Projected Run 001",
        ),
        storage_root=storage_root,
    )
    if not create_run.created:
        raise AssertionError(create_run.to_dict())

    read_model = {
        "schema": "measurement_record_read_model_v0",
        "record": {
            "record_id": "projected-run-001",
            "record_dir": "records/projected-run-001",
            "lifecycle_state": "complete",
        },
    }
    (storage_root / "records" / "projected-run-001" / "record-read-model.json").write_text(
        json.dumps(read_model),
        encoding="utf-8",
    )


class MeasurementRecordLegacyStorageInventoryPrototypeTest(unittest.TestCase):
    def test_records_legacy_run_as_storage_shell_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = record_legacy_measurement_run_from_request(
                _legacy_request(),
                storage_root=storage_root,
            )
            manifest = json.loads(
                (storage_root / "records" / "legacy-run-001" / "record-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            receipt = json.loads(
                (storage_root / "records" / "legacy-run-001" / "legacy-run-receipt.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(run.classification, "recorded_legacy_run")
        self.assertTrue(run.recorded)
        self.assertEqual(manifest["record"]["lifecycle_state"], "created")
        self.assertEqual(manifest["creation"]["source_kind"], "legacy_system")
        self.assertEqual(manifest["primary_data"], {"state": "not_recorded", "references": []})
        self.assertEqual(receipt["schema"], LEGACY_RUN_RECEIPT_SCHEMA)
        self.assertEqual(receipt["legacy_run"]["legacy_system_id"], "legacy-labview")
        self.assertEqual(receipt["legacy_run"]["legacy_run_id"], "lv-run-001")
        self.assertEqual(len(receipt["declared_locators"]), 2)
        self.assertEqual(
            receipt["operation"]["classification"],
            "legacy_run_recorded_for_review",
        )

    def test_unapproved_legacy_run_does_not_mutate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = record_legacy_measurement_run_from_request(
                _legacy_request(approval_state="needs_review"),
                storage_root=storage_root,
            )

            self.assertFalse((storage_root / "records").exists())

        self.assertEqual(run.classification, "blocked_before_legacy_run_record")
        self.assertFalse(run.recorded)

    def test_legacy_receipt_write_failure_rolls_back_record_shell(self) -> None:
        def fail_receipt_write(_path: Path, _content: bytes) -> None:
            raise OSError("simulated legacy receipt failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            run = record_legacy_measurement_run_from_request(
                _legacy_request(),
                storage_root=storage_root,
                receipt_writer=fail_receipt_write,
            )

            self.assertFalse((storage_root / "records" / "legacy-run-001").exists())

        self.assertEqual(run.classification, "rolled_back_after_legacy_receipt_failure")
        self.assertTrue(run.rollback_performed)
        self.assertIn("simulated legacy receipt failure", run.record_error or "")

    def test_storage_inventory_lists_legacy_and_projected_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            record_legacy_measurement_run_from_request(
                _legacy_request(),
                storage_root=storage_root,
            )
            _write_minimal_projected_record(storage_root)

            run = list_measurement_record_storage_from_request(
                MeasurementRecordStorageInventoryRequest(request_id="inventory-records"),
                storage_root=storage_root,
            )

        self.assertEqual(run.classification, "measurement_record_storage_inventory_ready")
        self.assertEqual(
            [entry["record_id"] for entry in run.entries], ["legacy-run-001", "projected-run-001"]
        )
        legacy_entry = run.entries[0]
        projected_entry = run.entries[1]
        self.assertEqual(legacy_entry["creation_source_kind"], "legacy_system")
        self.assertEqual(legacy_entry["legacy_run"]["state"], "present")
        self.assertEqual(legacy_entry["legacy_run"]["legacy_run_id"], "lv-run-001")
        self.assertEqual(legacy_entry["primary_data"]["state"], "not_recorded")
        self.assertEqual(projected_entry["read_model"]["state"], "present")
        self.assertEqual(projected_entry["read_model"]["lifecycle_state"], "complete")

    def test_raw_source_inventory_reports_missing_legacy_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            record_legacy_measurement_run_from_request(
                _legacy_request(),
                storage_root=storage_root,
            )
            (storage_root / "records" / "legacy-run-001" / "legacy-run-receipt.json").unlink()

            run = list_measurement_record_storage_from_request(
                _inventory_request(),
                storage_root=storage_root,
            )

        self.assertEqual(
            run.classification,
            "measurement_record_storage_inventory_review_needed",
        )
        self.assertEqual(run.review_findings[0]["code"], "legacy_receipt_missing")
        self.assertEqual(run.entries[0]["legacy_run"]["state"], "missing")
        self.assertEqual(run.to_dict()["next_action"], "review_storage_inventory_findings")


if __name__ == "__main__":
    unittest.main()
