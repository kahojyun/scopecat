from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import HandoffReceivingReviewRequest, run_receiving_gate

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _receiving_gate_source() -> dict:
    return {
        "receiving_gate_schema": "scopecat.handoff_receiving_gate.v0",
        "receiving_gate_policy": {
            "workflow_authority": "approved_receiving_review_request",
            "package_open": "read_only_declared_preview",
            "integrity_observation": "read_only_package_local_member_observation",
            "acceptance_gate": "require_approved_review_and_declared_integrity_verified",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "package_root_concurrency": "not_supported",
            "schema_inference": "not_performed",
            "dataframe_adapter": "not_defined",
            "interactive_gui": "not_defined",
            "shared_measurement_schema": "not_defined",
        },
        "receiving_review_request": {
            "request_id": "receive-handoff-package-legacy-rabi-001",
            "review": {
                "approval_state": "approved",
                "reviewed_package_id": "handoff-package-legacy-rabi-001",
                "reviewed_preview_classification": "needs_review_before_acceptance",
                "reviewed_integrity_classification": "declared_integrity_verified",
            },
        },
    }


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


class HandoffEngineeringPrototypeReceivingTest(unittest.TestCase):
    def test_receiving_gate_allows_reviewed_verified_package_without_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))

            run = run_receiving_gate(_receiving_gate_source(), package_dir=package_dir)
            summary = run.to_dict()
            records_exist = (Path(temp_dir) / "records").exists()

        self.assertEqual(run.classification, "ready_for_acceptance_mutation")
        self.assertTrue(run.acceptance_allowed)
        self.assertEqual(summary["artifact_posture"], "local_receiving_gate_receipt")
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            summary["package"]["integrity_classification"],
            "declared_integrity_verified",
        )
        self.assertTrue(summary["acceptance_gate"]["allowed"])
        self.assertEqual(
            summary["receiving_review"],
            {
                "classification": "ready_for_acceptance_mutation",
                "acceptance_allowed": True,
                "block_reason": None,
                "next_action": "build_import_plan_for_reviewed_package",
                "retry_requires": None,
            },
        )
        self.assertIn("storage_mutation", summary["does_not_claim"])
        self.assertFalse(records_exist)

    def test_receiving_gate_blocks_when_integrity_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            source = _receiving_gate_source()
            source["receiving_review_request"]["review"]["reviewed_integrity_classification"] = (
                "integrity_review_required"
            )

            run = run_receiving_gate(source, package_dir=package_dir)
            summary = run.to_dict()
            records_exist = (temp_root / "records").exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.acceptance_allowed)
        self.assertEqual(
            summary["integrity_observation"]["classification"],
            "integrity_review_required",
        )
        self.assertFalse(summary["acceptance_gate"]["allowed"])
        self.assertEqual(
            summary["receiving_review"],
            {
                "classification": "blocked_before_acceptance",
                "acceptance_allowed": False,
                "block_reason": "package_integrity_review_required",
                "next_action": "review_package_integrity_before_import_planning",
                "retry_requires": "fresh_matching_package_open_and_integrity_observation",
            },
        )
        self.assertFalse(records_exist)

    def test_receiving_gate_returns_blocked_review_when_declared_primary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()
            source = _receiving_gate_source()
            source["receiving_review_request"]["review"]["reviewed_integrity_classification"] = (
                "integrity_review_required"
            )

            run = run_receiving_gate(source, package_dir=package_dir)
            summary = run.to_dict()
            records_exist = (temp_root / "records").exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.acceptance_allowed)
        self.assertEqual(
            summary["integrity_observation"]["classification"],
            "integrity_review_required",
        )
        self.assertEqual(
            summary["package"]["open_error"],
            "handoff package primary data is unavailable",
        )
        self.assertEqual(
            summary["receiving_review"]["block_reason"],
            "package_integrity_review_required",
        )
        self.assertFalse(records_exist)

    def test_rejects_unapproved_request_before_open_or_integrity_observation(self) -> None:
        source = _receiving_gate_source()
        source["receiving_review_request"]["review"]["approval_state"] = "needs_review"

        with tempfile.TemporaryDirectory() as temp_dir:
            missing_package = Path(temp_dir) / PACKAGE.name
            with self.assertRaisesRegex(ValueError, "requires approved review"):
                run_receiving_gate(source, package_dir=missing_package)

    def test_rejects_reviewed_package_id_mismatch(self) -> None:
        source = _receiving_gate_source()
        source["receiving_review_request"]["review"]["reviewed_package_id"] = "different-package"

        with self.assertRaisesRegex(ValueError, "reviewed package id"):
            run_receiving_gate(source, package_dir=PACKAGE)

    def test_rejects_reviewed_preview_classification_mismatch(self) -> None:
        source = _receiving_gate_source()
        source["receiving_review_request"]["review"]["reviewed_preview_classification"] = (
            "preview_ready_for_opening"
        )

        with self.assertRaisesRegex(ValueError, "reviewed preview classification"):
            run_receiving_gate(source, package_dir=PACKAGE)

    def test_rejects_reviewed_integrity_classification_mismatch(self) -> None:
        source = _receiving_gate_source()
        source["receiving_review_request"]["review"]["reviewed_integrity_classification"] = (
            "integrity_review_required"
        )

        with self.assertRaisesRegex(ValueError, "reviewed integrity classification"):
            run_receiving_gate(source, package_dir=PACKAGE)

    def test_rejects_source_with_acceptance_destination(self) -> None:
        source = _receiving_gate_source()
        source["receiving_review_request"]["acceptance"] = {
            "destination": "must-not-be-accepted-by-read-only-gate"
        }

        with self.assertRaisesRegex(ValueError, "fields are unsupported"):
            run_receiving_gate(source, package_dir=PACKAGE)

    def test_typed_receiving_review_request_validates_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "public-safe identifier"):
            HandoffReceivingReviewRequest(
                request_id="receive/handoff",
                reviewed_package_id="handoff-package-legacy-rabi-001",
                reviewed_preview_classification="needs_review_before_acceptance",
                reviewed_integrity_classification="declared_integrity_verified",
            )


if __name__ == "__main__":
    unittest.main()
