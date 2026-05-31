from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.reviewed_legacy_sidecar_evidence_append_receipt import (
    write_reviewed_legacy_sidecar_evidence_append_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "reviewed_legacy_sidecar_evidence_append_receipt"
    / "basic_receipt"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "evidence-append-receipt-input.json").read_text(encoding="utf-8"))


def _prepare_storage(temp_dir: str) -> Path:
    storage_root = Path(temp_dir) / "storage"
    shutil.copytree(FIXTURE / "existing-storage", storage_root)
    return storage_root


class ReviewedLegacySidecarEvidenceAppendReceiptSummaryCandidateTest(unittest.TestCase):
    def test_writes_expected_review_evidence_receipt_without_replacing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            manifest_path = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "record-manifest.json"
            )
            original_manifest = manifest_path.read_text(encoding="utf-8")

            summary = write_reviewed_legacy_sidecar_evidence_append_receipt(
                _load_input(),
                storage_root=storage_root,
            )
            expected = json.loads(
                (FIXTURE / "expected-evidence-append-receipt-summary.json").read_text(
                    encoding="utf-8"
                )
            )["candidate_summary"]

            self.assertEqual(summary, expected)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), original_manifest)
            self.assertFalse(
                (
                    storage_root
                    / "records"
                    / "legacy-sidecar-measurement-0001"
                    / "review-evidence.lock"
                ).exists()
            )
            receipt = json.loads(
                (
                    storage_root
                    / "records"
                    / "legacy-sidecar-measurement-0001"
                    / "review-evidence"
                    / "legacy-sidecar-evidence-receipt-0001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["receipt_id"], "legacy-sidecar-evidence-receipt-0001")
            self.assertEqual(receipt["measurement_id"], "legacy-sidecar-measurement-0001")
            self.assertEqual(receipt["receipt_effects"]["manifest_update"], "not_performed")
            self.assertEqual(receipt["receipt_effects"]["primary_data_import"], "not_performed")
            self.assertEqual(receipt["receipt_effects"]["reference_repair"], "not_performed")
            self.assertEqual(receipt["receipt_effects"]["measurement_validity"], "not_claimed")

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_append_receipt_policy"]["primary_data_import"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "primary_data_import"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=_prepare_storage(temp_dir),
                )

        source = _load_input()
        source["evidence_append_receipt_policy"]["measurement_validity"] = "claimed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "measurement_validity"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["evidence_append_receipt_policy"]["primary_data_copy"] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "expected shape"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_append_intent_must_be_approved_and_non_mutating(self) -> None:
        source = _load_input()
        source["reviewed_legacy_sidecar_append_intent_summary"]["append_intent"][
            "approval_state"
        ] = "deferred"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "approved append intent"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=_prepare_storage(temp_dir),
                )

        source = _load_input()
        source["reviewed_legacy_sidecar_append_intent_summary"]["intent_effects"][
            "record_write"
        ] = "performed"

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "record_write"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=_prepare_storage(temp_dir),
                )

    def test_write_request_must_match_append_intent(self) -> None:
        cases = [
            ("append_intent_request_id", "other-intent", "append_intent_request_id"),
            ("measurement_id", "other-measurement", "measurement_id"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["write_request"][field] = value

                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(ValueError, message):
                        write_reviewed_legacy_sidecar_evidence_append_receipt(
                            source,
                            storage_root=_prepare_storage(temp_dir),
                        )

    def test_manifest_identity_mismatch_is_refused_without_writing_receipt(self) -> None:
        source = _load_input()
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
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest id"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (
                    storage_root / "records" / "legacy-sidecar-measurement-0001" / "review-evidence"
                ).exists()
            )
            self.assertFalse(
                (
                    storage_root
                    / "records"
                    / "legacy-sidecar-measurement-0001"
                    / "review-evidence.lock"
                ).exists()
            )

    def test_existing_receipt_is_refused_without_overwrite(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            receipt = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence"
                / "legacy-sidecar-evidence-receipt-0001.json"
            )
            receipt.parent.mkdir()
            receipt.write_text("existing\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already exists"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=storage_root,
                )

            self.assertEqual(receipt.read_text(encoding="utf-8"), "existing\n")
            self.assertFalse(
                (
                    storage_root
                    / "records"
                    / "legacy-sidecar-measurement-0001"
                    / "review-evidence.lock"
                ).exists()
            )

    def test_existing_lock_is_refused_without_writing_receipt(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            lock = (
                storage_root
                / "records"
                / "legacy-sidecar-measurement-0001"
                / "review-evidence.lock"
            )
            lock.write_text("owned elsewhere\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "target already exists"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=storage_root,
                )

            self.assertFalse(
                (
                    storage_root / "records" / "legacy-sidecar-measurement-0001" / "review-evidence"
                ).exists()
            )

    def test_missing_record_dir_is_refused_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()

            with self.assertRaisesRegex(ValueError, "record directory is unavailable"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    _load_input(),
                    storage_root=storage_root,
                )

            self.assertFalse((storage_root / "records").exists())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = _prepare_storage(temp_dir)
            record = storage_root / "records" / "legacy-sidecar-measurement-0001"
            outside = storage_root / "outside"
            outside.mkdir()
            (record / "review-evidence").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                write_reviewed_legacy_sidecar_evidence_append_receipt(
                    source,
                    storage_root=storage_root,
                )

            self.assertTrue((record / "review-evidence").is_symlink())

    def test_boundary_output_keeps_primary_import_repair_and_validity_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-evidence-append-receipt-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("storage-mutating", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["receipt_effects"]["primary_data_import"], "not_performed")
        self.assertEqual(candidate["receipt_effects"]["reference_repair"], "not_performed")
        self.assertEqual(candidate["receipt_effects"]["measurement_validity"], "not_claimed")
        self.assertEqual(
            attention["manifest_not_replaced"]["does_not_claim"],
            "read_model_refresh_or_manifest_merge",
        )
        self.assertIn(
            "manifest replacement or read-model refresh", expected["decisions_not_earned"]
        )


if __name__ == "__main__":
    unittest.main()
