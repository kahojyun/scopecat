from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.legacy_evidence_receipt_read_view import (
    read_legacy_evidence_receipts,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_evidence_receipt_read_view" / "basic_read"


def _load_input() -> dict:
    return json.loads((FIXTURE / "evidence-receipt-read-input.json").read_text(encoding="utf-8"))


def _prepare_storage(temp_dir: str) -> Path:
    storage_root = Path(temp_dir) / "storage"
    shutil.copytree(FIXTURE / "existing-storage", storage_root)
    return storage_root


class LegacyEvidenceReceiptReadViewSummaryCandidateTest(unittest.TestCase):
    def test_reads_expected_legacy_evidence_receipt_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = read_legacy_evidence_receipts(
                _load_input(),
                storage_root=_prepare_storage(temp_dir),
            )
        expected = json.loads(
            (FIXTURE / "expected-evidence-receipt-read-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertEqual(summary["classification"], "legacy_evidence_receipt_read_view_ready")
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)

    def test_read_view_surfaces_receipt_evidence_without_primary_data_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = read_legacy_evidence_receipts(
                _load_input(),
                storage_root=_prepare_storage(temp_dir),
            )
        receipt = summary["receipt_view"]["receipts"][0]
        evidence = receipt["planned_review_evidence"]["legacy_locator_observation_review"]

        self.assertEqual(receipt["status"], "observed")
        self.assertEqual(receipt["receipt_id"], "legacy-sidecar-evidence-receipt-0001")
        self.assertEqual(evidence["fact_posture"], "review_debug_evidence")
        self.assertEqual(evidence["does_not_claim"], "primary_data_import_or_preview_verification")
        self.assertEqual(summary["read_effects"]["primary_data_read"], "not_performed")
        self.assertEqual(summary["read_effects"]["storage_scan"], "not_performed")

    def test_missing_receipt_is_review_finding_not_repair(self) -> None:
        source = _load_input()
        source["read_request"]["receipt_paths"] = [
            "records/legacy-sidecar-measurement-0001/review-evidence/missing.json"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

        self.assertEqual(
            summary["classification"], "legacy_evidence_receipt_read_view_needs_review"
        )
        self.assertEqual(summary["receipt_view"]["status_counts"], {"unavailable": 1})
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["legacy_evidence_receipt_unavailable"],
        )
        self.assertEqual(
            summary["review_findings"][0]["does_not_claim"],
            "repair_import_or_validity_decision",
        )

    def test_malformed_receipt_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence"
                / "legacy-sidecar-evidence-receipt-0001.json"
            )
            receipt.write_text("{not-json\n", encoding="utf-8")

            summary = read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

        self.assertEqual(summary["receipt_view"]["status_counts"], {"malformed": 1})
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["legacy_evidence_receipt_malformed"],
        )

    def test_receipt_measurement_mismatch_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt_path = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence"
                / "legacy-sidecar-evidence-receipt-0001.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["measurement_id"] = "other-measurement"
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

            summary = read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

        self.assertEqual(summary["receipt_view"]["status_counts"], {"observed_with_findings": 1})
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["legacy_evidence_receipt_measurement_mismatch"],
        )

    def test_receipt_effect_claim_is_review_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt_path = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence"
                / "legacy-sidecar-evidence-receipt-0001.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["receipt_effects"]["primary_data_import"] = "performed"
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

            summary = read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

        self.assertEqual(summary["receipt_view"]["status_counts"], {"observed_with_findings": 1})
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["legacy_evidence_receipt_effect_claim"],
        )
        self.assertIn("primary_data_import", summary["review_findings"][0]["basis"])

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_receipt_read_policy"]["primary_data_read"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "primary_data_read"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

        source = _load_input()
        source["evidence_receipt_read_policy"]["storage_mutation"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "storage_mutation"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_receipt_read_policy"]["read_model_refresh"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected shape"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

    def test_manifest_identity_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            manifest_path = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "record-manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["measurement_record_id"] = "other-measurement"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest id"):
                read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

    def test_receipt_paths_must_be_declared_unique_and_under_record_dir(self) -> None:
        source = _load_input()
        source["read_request"]["receipt_paths"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "non-empty"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

        source = _load_input()
        source["read_request"]["receipt_paths"] = [
            "records/legacy-sidecar-measurement-0001/review-evidence/a.json",
            "records/legacy-sidecar-measurement-0001/review-evidence/a.json",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unique"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

        source = _load_input()
        source["read_request"]["receipt_paths"] = ["records/other/receipt.json"]

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "receipt_path"):
                read_legacy_evidence_receipts(source, storage_root=_prepare_storage(temp_dir))

    def test_receipt_symlink_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence"
                / "legacy-sidecar-evidence-receipt-0001.json"
            )
            receipt.unlink()
            receipt.symlink_to("redirected.json")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

            self.assertTrue(receipt.is_symlink())

    def test_receipt_parent_symlink_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            record = storage_root / "records" / "legacy-sidecar-measurement-0001"
            shutil.rmtree(record / "review-evidence")
            outside = storage_root / "outside"
            outside.mkdir()
            (record / "review-evidence").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                read_legacy_evidence_receipts(_load_input(), storage_root=storage_root)

            self.assertTrue((record / "review-evidence").is_symlink())

    def test_boundary_output_keeps_scan_import_repair_and_validity_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-evidence-receipt-read-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("read-only view", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["read_effects"]["storage_scan"], "not_performed")
        self.assertEqual(candidate["read_effects"]["primary_data_read"], "not_performed")
        self.assertEqual(candidate["read_effects"]["reference_repair"], "not_performed")
        self.assertEqual(candidate["read_effects"]["measurement_validity"], "not_claimed")
        self.assertEqual(
            attention["receipt_read_view_only"]["does_not_claim"],
            "storage_scan_or_read_model_refresh",
        )
        self.assertIn("storage scan or read-model refresh", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
