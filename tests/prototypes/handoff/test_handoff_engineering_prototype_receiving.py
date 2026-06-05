from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import HandoffReceivingReviewRequest, run_receiving_gate_from_request

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)


def _receiving_request(**overrides: str) -> HandoffReceivingReviewRequest:
    values = {
        "request_id": "receive-handoff-package-legacy-rabi-001",
        "reviewed_package_id": "handoff-package-legacy-rabi-001",
        "reviewed_preview_classification": "needs_review_before_acceptance",
        "reviewed_integrity_classification": "declared_integrity_verified",
    }
    values.update(overrides)
    return HandoffReceivingReviewRequest(**values)


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


class HandoffEngineeringPrototypeReceivingTest(unittest.TestCase):
    def test_receiving_gate_allows_reviewed_verified_package_without_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))

            run = run_receiving_gate_from_request(_receiving_request(), package_dir=package_dir)
            summary = run.to_dict()
            records_exist = (Path(temp_dir) / "records").exists()

        self.assertEqual(run.classification, "ready_for_acceptance_mutation")
        self.assertTrue(run.acceptance_allowed)
        self.assertEqual(summary["artifact_posture"], "local_receiving_gate_receipt")
        self.assertEqual(summary["classification"], "ready_for_acceptance_mutation")
        self.assertIsNone(summary["block_reason"])
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(
            summary["package"]["integrity_classification"],
            "declared_integrity_verified",
        )
        self.assertTrue(summary["acceptance_gate"]["allowed"])
        self.assertFalse(records_exist)

    def test_receiving_gate_blocks_when_integrity_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").write_text(
                "drive_frequency,signal\n5.00,0.99\n",
                encoding="utf-8",
            )
            run = run_receiving_gate_from_request(
                _receiving_request(
                    reviewed_integrity_classification="integrity_review_required",
                ),
                package_dir=package_dir,
            )
            summary = run.to_dict()
            records_exist = (temp_root / "records").exists()

        self.assertEqual(run.classification, "blocked_before_acceptance")
        self.assertFalse(run.acceptance_allowed)
        self.assertEqual(
            summary["integrity_observation"]["classification"],
            "integrity_review_required",
        )
        self.assertEqual(summary["block_reason"], "package_integrity_review_required")
        self.assertFalse(summary["acceptance_gate"]["allowed"])
        self.assertFalse(records_exist)

    def test_receiving_gate_returns_blocked_review_when_declared_primary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = _copy_package(temp_root)
            (package_dir / "measurements" / "legacy-rabi-001" / "primary.csv").unlink()
            run = run_receiving_gate_from_request(
                _receiving_request(
                    reviewed_integrity_classification="integrity_review_required",
                ),
                package_dir=package_dir,
            )
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
        self.assertEqual(summary["block_reason"], "package_integrity_review_required")
        self.assertFalse(records_exist)

    def test_rejects_reviewed_package_id_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed package id"):
            run_receiving_gate_from_request(
                _receiving_request(reviewed_package_id="different-package"),
                package_dir=PACKAGE,
            )

    def test_rejects_reviewed_preview_classification_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed preview classification"):
            run_receiving_gate_from_request(
                _receiving_request(
                    reviewed_preview_classification="preview_ready_for_opening",
                ),
                package_dir=PACKAGE,
            )

    def test_rejects_reviewed_integrity_classification_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "reviewed integrity classification"):
            run_receiving_gate_from_request(
                _receiving_request(
                    reviewed_integrity_classification="integrity_review_required",
                ),
                package_dir=PACKAGE,
            )

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
