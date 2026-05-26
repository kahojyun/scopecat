from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_receiving_workflow import (
    run_handoff_package_receiving_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _receiving_source() -> dict:
    return {
        "receiving_schema": "scopecat.handoff_package_receiving_workflow.v0",
        "receiving_policy": {
            "workflow_authority": "approved_receiving_workflow_request",
            "package_inspection": "read_only_visual_inspection_workflow",
            "integrity_observation": "read_only_package_local_member_observation",
            "integrity_gate": "require_declared_integrity_verified",
            "acceptance_authority": "delegate_to_handoff_package_acceptance",
            "storage_mutation": "acceptance_candidate_only_after_gate",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "package_root_concurrency": "not_supported",
            "schema_inference": "not_performed",
            "dataframe_adapter": "not_defined",
            "interactive_gui": "not_defined",
            "shared_measurement_schema": "not_defined",
        },
        "receiving_request": {
            "request_id": "receive-handoff-package-legacy-rabi-001",
            "review": {
                "approval_state": "approved",
                "reviewed_package_id": "handoff-package-legacy-rabi-001",
                "reviewed_preview_classification": "needs_review_before_acceptance",
                "reviewed_integrity_classification": "declared_integrity_verified",
            },
            "acceptance": {
                "destination": {
                    "path_kind": "relative_storage_path_under_caller_root",
                    "collision_policy": "no_overwrite",
                },
                "materialization": {
                    "selected_measurements": "copy_primary_data_into_storage",
                    "linked_context": "reference_only",
                    "source_package_identity": "preserve_package_reference",
                },
                "selected_measurements": [
                    {
                        "measurement_record_id": "legacy-rabi-001",
                        "record_dir": "records/legacy-rabi-001",
                        "primary_data_path": "records/legacy-rabi-001/primary.csv",
                        "manifest_path": "records/legacy-rabi-001/record-manifest.json",
                    }
                ],
            },
        },
    }


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


class HandoffPackageReceivingWorkflowCandidateTest(unittest.TestCase):
    def test_inspects_verifies_and_accepts_reviewed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            artifact_output_dir = temp_root / "inspection"
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            receipt = run_handoff_package_receiving_workflow(
                _receiving_source(),
                package_dir=PACKAGE,
                artifact_output_dir=artifact_output_dir,
                storage_root=storage_root,
            )

            artifact_path = Path(receipt["inspection"]["local_visual_artifact"]["local_path"])
            primary_path = storage_root / "records" / "legacy-rabi-001" / "primary.csv"
            manifest_path = storage_root / "records" / "legacy-rabi-001" / "record-manifest.json"
            artifact_exists = artifact_path.is_file()
            primary_exists = primary_path.is_file()
            accepted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(receipt["artifact_posture"], "local_receiving_workflow_receipt")
        self.assertEqual(receipt["workflow_classification"], "accepted_into_storage")
        self.assertEqual(receipt["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            receipt["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertEqual(
            receipt["package"]["integrity_classification"],
            "declared_integrity_verified",
        )
        self.assertTrue(receipt["inspection"]["performed"])
        self.assertEqual(artifact_path.name, "handoff-package-visual-review.html")
        self.assertTrue(artifact_exists)
        self.assertTrue(receipt["integrity_observation"]["performed"])
        self.assertEqual(receipt["integrity_observation"]["member_count"], 1)
        self.assertTrue(receipt["acceptance_gate"]["allowed"])
        self.assertTrue(receipt["acceptance"]["performed"])
        self.assertEqual(receipt["acceptance"]["storage_write"]["record_count"], 1)
        self.assertTrue(primary_exists)
        self.assertEqual(
            accepted_manifest["source"]["package_id"],
            "handoff-package-legacy-rabi-001",
        )

    def test_blocks_acceptance_when_integrity_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            artifact_output_dir = temp_root / "inspection"
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            source = _receiving_source()
            source["receiving_request"]["review"]["reviewed_integrity_classification"] = (
                "integrity_review_required"
            )

            receipt = run_handoff_package_receiving_workflow(
                source,
                package_dir=package_dir,
                artifact_output_dir=artifact_output_dir,
                storage_root=storage_root,
            )
            artifact_path = Path(receipt["inspection"]["local_visual_artifact"]["local_path"])
            artifact_exists = artifact_path.is_file()
            records_exist = (storage_root / "records").exists()

        self.assertEqual(receipt["workflow_classification"], "blocked_before_acceptance")
        self.assertTrue(receipt["inspection"]["performed"])
        self.assertTrue(artifact_exists)
        self.assertTrue(receipt["integrity_observation"]["performed"])
        self.assertEqual(
            receipt["integrity_observation"]["classification"],
            "integrity_review_required",
        )
        self.assertFalse(receipt["acceptance_gate"]["allowed"])
        self.assertFalse(receipt["acceptance"]["performed"])
        self.assertFalse(records_exist)

    def test_rejects_reviewed_package_id_mismatch(self) -> None:
        source = _receiving_source()
        source["receiving_request"]["review"]["reviewed_package_id"] = "different-package"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "reviewed package id"):
                run_handoff_package_receiving_workflow(
                    source,
                    package_dir=PACKAGE,
                    artifact_output_dir=temp_root / "inspection",
                    storage_root=storage_root,
                )

            records_exist = (storage_root / "records").exists()

        self.assertFalse(records_exist)

    def test_rejects_reviewed_preview_classification_mismatch(self) -> None:
        source = _receiving_source()
        source["receiving_request"]["review"]["reviewed_preview_classification"] = (
            "preview_ready_for_opening"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "reviewed preview classification"):
                run_handoff_package_receiving_workflow(
                    source,
                    package_dir=PACKAGE,
                    artifact_output_dir=temp_root / "inspection",
                    storage_root=storage_root,
                )

            records_exist = (storage_root / "records").exists()

        self.assertFalse(records_exist)

    def test_rejects_reviewed_integrity_classification_mismatch(self) -> None:
        source = _receiving_source()
        source["receiving_request"]["review"]["reviewed_integrity_classification"] = (
            "integrity_review_required"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "reviewed integrity classification"):
                run_handoff_package_receiving_workflow(
                    source,
                    package_dir=PACKAGE,
                    artifact_output_dir=temp_root / "inspection",
                    storage_root=storage_root,
                )

            records_exist = (storage_root / "records").exists()

        self.assertFalse(records_exist)

    def test_rejects_unapproved_request_before_inspection_or_storage(self) -> None:
        source = _receiving_source()
        source["receiving_request"]["review"]["approval_state"] = "needs_review"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "requires approved review"):
                run_handoff_package_receiving_workflow(
                    source,
                    package_dir=PACKAGE,
                    artifact_output_dir=temp_root / "inspection",
                    storage_root=storage_root,
                )

            inspection_exists = (temp_root / "inspection").exists()
            records_exist = (storage_root / "records").exists()

        self.assertFalse(inspection_exists)
        self.assertFalse(records_exist)

    def test_rejects_artifact_output_inside_storage_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            artifact_output_dir = storage_root / "inspection"

            with self.assertRaisesRegex(ValueError, "outside the storage root"):
                run_handoff_package_receiving_workflow(
                    _receiving_source(),
                    package_dir=PACKAGE,
                    artifact_output_dir=artifact_output_dir,
                    storage_root=storage_root,
                )

            artifact_exists = artifact_output_dir.exists()
            records_exist = (storage_root / "records").exists()

        self.assertFalse(artifact_exists)
        self.assertFalse(records_exist)

    def test_rejects_artifact_output_inside_package_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            storage_root = temp_root / "storage"
            storage_root.mkdir()
            artifact_output_dir = package_dir / "inspection"

            with self.assertRaisesRegex(ValueError, "outside the package tree"):
                run_handoff_package_receiving_workflow(
                    _receiving_source(),
                    package_dir=package_dir,
                    artifact_output_dir=artifact_output_dir,
                    storage_root=storage_root,
                )

            artifact_exists = artifact_output_dir.exists()
            records_exist = (storage_root / "records").exists()

        self.assertFalse(artifact_exists)
        self.assertFalse(records_exist)

    def test_rejects_artifact_target_symlink_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            artifact_output_dir = temp_root / "inspection"
            storage_root.mkdir()
            artifact_output_dir.mkdir()
            (artifact_output_dir / "handoff-package-visual-review.html").symlink_to(
                storage_root / "records" / "unexpected.html",
            )

            with self.assertRaisesRegex(ValueError, "target must not be a symlink"):
                run_handoff_package_receiving_workflow(
                    _receiving_source(),
                    package_dir=PACKAGE,
                    artifact_output_dir=artifact_output_dir,
                    storage_root=storage_root,
                )

            records_exist = (storage_root / "records").exists()

        self.assertFalse(records_exist)


if __name__ == "__main__":
    unittest.main()
