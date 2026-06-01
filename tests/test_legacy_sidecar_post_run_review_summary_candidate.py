from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_sidecar_post_run_review import (
    build_legacy_sidecar_post_run_review_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_sidecar_post_run_review" / "basic_review"


def _load_input() -> dict:
    return json.loads((FIXTURE / "sidecar-post-run-review-input.json").read_text(encoding="utf-8"))


class LegacySidecarPostRunReviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_legacy_sidecar_post_run_review_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-sidecar-post-run-review-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)

    def test_ready_projection_carries_sidecar_sections_without_observation(self) -> None:
        summary = build_legacy_sidecar_post_run_review_summary(_load_input())
        sections = summary["review_sections"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["classification"], "legacy_sidecar_post_run_ready")
        self.assertEqual(sections["lifecycle"]["lifecycle"]["state"], "completed")
        self.assertEqual(
            sections["legacy_locators"]["classification"], "legacy_locator_review_ready"
        )
        self.assertEqual(sections["primary_data"]["primary_data_ref_count"], 1)
        self.assertEqual(sections["supporting_evidence"]["supporting_evidence_ref_count"], 2)
        self.assertEqual(
            attention["fresh_observation_not_performed"]["does_not_claim"],
            "locator_openability_or_data_validity",
        )

    def test_locator_review_findings_drive_locator_review_classification(self) -> None:
        source = _load_input()
        locator_review = source["legacy_locator_sufficiency_review_summary"]
        locator_review["classification"] = "legacy_locator_review_insufficient"
        locator_review["locator_findings"] = [
            {
                "code": "legacy_locator_operator_note_only",
                "severity": "review",
                "target_id": "legacy-sidecar-measurement-0001",
                "basis": "Only operator-note locators are available.",
                "does_not_claim": "legacy_record_missing",
            }
        ]
        locator_review["targets"][0]["classification"] = "locator_insufficient_operator_note_only"

        summary = build_legacy_sidecar_post_run_review_summary(source)
        finding = summary["review_findings"][0]

        self.assertEqual(
            summary["classification"],
            "legacy_sidecar_post_run_needs_locator_review",
        )
        self.assertEqual(summary["review_finding_count"], 1)
        self.assertEqual(finding["source_section"], "legacy_locator_review")
        self.assertEqual(finding["does_not_claim"], "legacy_record_missing")

    def test_locator_unavailable_classification_is_preserved(self) -> None:
        source = _load_input()
        locator_review = source["legacy_locator_sufficiency_review_summary"]
        locator_review["classification"] = "legacy_locator_review_unavailable"
        locator_review["locator_findings"] = [
            {
                "code": "legacy_locator_unavailable",
                "severity": "review",
                "target_id": "primary-legacy-table-0001",
                "basis": "No declared locator is currently available for review.",
                "does_not_claim": "legacy_record_missing_or_deleted",
            }
        ]

        summary = build_legacy_sidecar_post_run_review_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_sidecar_post_run_locator_unavailable",
        )

    def test_partial_and_failed_sidecar_lifecycle_drive_review_classification(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["measurement_record"]["lifecycle"]["state"] = "partial"

        summary = build_legacy_sidecar_post_run_review_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_sidecar_post_run_partial_needs_review",
        )

        source = _load_input()
        source["legacy_run_sidecar_summary"]["measurement_record"]["lifecycle"]["state"] = "failed"

        summary = build_legacy_sidecar_post_run_review_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_sidecar_post_run_failed_needs_review",
        )

    def test_sidecar_manifest_findings_are_carried(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["manifest_findings"] = [
            {
                "code": "legacy_run_partial",
                "severity": "review",
                "basis": "The legacy run stopped before expected completion.",
                "does_not_claim": "hardware_failure_or_measurement_invalid",
            }
        ]

        summary = build_legacy_sidecar_post_run_review_summary(source)

        self.assertEqual(summary["classification"], "legacy_sidecar_post_run_needs_attention")
        self.assertEqual(summary["review_findings"][0]["source_section"], "sidecar_manifest")

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["sidecar_post_run_review_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_legacy_sidecar_post_run_review_summary(source)

        source = _load_input()
        source["sidecar_post_run_review_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_legacy_sidecar_post_run_review_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["sidecar_post_run_review_policy"]["review_gui"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_sidecar_post_run_review_summary(source)

    def test_locator_review_must_match_sidecar_identity_and_classification(self) -> None:
        source = _load_input()
        source["legacy_locator_sufficiency_review_summary"]["source_sidecar"]["measurement_id"] = (
            "other-measurement"
        )

        with self.assertRaisesRegex(ValueError, "measurement_id"):
            build_legacy_sidecar_post_run_review_summary(source)

        source = _load_input()
        source["legacy_locator_sufficiency_review_summary"]["source_sidecar"]["classification"] = (
            "mutated"
        )

        with self.assertRaisesRegex(ValueError, "source classification"):
            build_legacy_sidecar_post_run_review_summary(source)

    def test_locator_review_must_cover_primary_data_targets(self) -> None:
        source = _load_input()
        source["legacy_locator_sufficiency_review_summary"]["targets"] = [
            target
            for target in source["legacy_locator_sufficiency_review_summary"]["targets"]
            if target["target_type"] != "primary_data_legacy_source"
        ]

        with self.assertRaisesRegex(ValueError, "primary data target"):
            build_legacy_sidecar_post_run_review_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_sidecar_post_run_review_summary(source)

        source["legacy_run_sidecar_summary"]["supporting_evidence_refs"][0]["label"] = "mutated"
        source["legacy_locator_sufficiency_review_summary"]["targets"][0]["locators"][0][
            "display"
        ] = "mutated"

        self.assertEqual(
            summary["review_sections"]["supporting_evidence"]["supporting_evidence_refs"][0][
                "label"
            ],
            "Run-adjacent parameter JSON snapshot",
        )
        self.assertEqual(
            summary["review_sections"]["legacy_locators"]["targets"][0]["locators"][0]["display"],
            "legacy-session-0001/record-0001",
        )

    def test_boundary_output_keeps_import_storage_and_repair_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-sidecar-post-run-review-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("not fresh observation", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(
            candidate["sidecar_post_run_review_policy"]["record_write"], "not_performed"
        )
        self.assertEqual(
            candidate["sidecar_post_run_review_policy"]["reference_repair"], "not_performed"
        )
        self.assertEqual(
            attention["legacy_import_not_performed"]["does_not_claim"],
            "import_acceptance_or_normalized_data",
        )
        self.assertIn("reference repair", " ".join(expected["decisions_not_earned"]))


if __name__ == "__main__":
    unittest.main()
