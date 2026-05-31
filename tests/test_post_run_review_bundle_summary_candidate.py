from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.post_run_review_bundle import (
    build_post_run_review_bundle_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "post_run_review_bundle" / "basic_bundle"


def _load_input() -> dict:
    return json.loads((FIXTURE / "bundle-input.json").read_text(encoding="utf-8"))


class PostRunReviewBundleSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_post_run_review_bundle_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-bundle-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_review_findings_are_grouped_without_measurement_validity_claim(self) -> None:
        summary = build_post_run_review_bundle_summary(_load_input())
        findings = summary["review_findings"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(summary["classification"], "post_run_review_needs_attention")
        self.assertEqual(summary["review_finding_count"], 2)
        self.assertEqual(
            {finding["source_section"] for finding in findings},
            {"context_status", "supporting_evidence"},
        )
        self.assertEqual(
            attention["primary_data_not_observed"]["does_not_claim"],
            "measurement_validity",
        )

    def test_evidence_and_primary_data_are_not_observed(self) -> None:
        summary = build_post_run_review_bundle_summary(_load_input())
        policy = summary["post_run_review_policy"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(policy["primary_data_observation"], "not_performed")
        self.assertEqual(policy["evidence_payload_import"], "not_performed")
        self.assertEqual(policy["file_observation"], "not_performed")
        self.assertEqual(
            attention["evidence_not_imported"]["does_not_claim"],
            "evidence_contents_verified",
        )

    def test_ready_classification_when_prior_summaries_have_no_findings(self) -> None:
        source = _load_input()
        source["context_status_summary"]["overall_classification"] = "ready_for_context_review"
        source["context_status_summary"]["status_findings"] = []
        source["running_evidence_update_summary"]["evidence_findings"] = []

        summary = build_post_run_review_bundle_summary(source)

        self.assertEqual(summary["classification"], "post_run_review_ready")
        self.assertEqual(summary["review_findings"], [])

    def test_blocked_classification_follows_context_status_block(self) -> None:
        source = _load_input()
        source["context_status_summary"]["overall_classification"] = "blocked_for_context_review"
        source["context_status_summary"]["context_statuses"][0]["classification"] = (
            "blocked_for_context_review"
        )
        source["context_status_summary"]["status_findings"][0]["severity"] = "block"
        source["context_status_summary"]["status_findings"][0]["finding"] = (
            "context_freshness_blocked"
        )

        summary = build_post_run_review_bundle_summary(source)

        self.assertEqual(summary["classification"], "post_run_review_blocked")

    def test_unrelated_context_status_does_not_block_post_run_review(self) -> None:
        source = _load_input()
        source["context_status_summary"]["overall_classification"] = "blocked_for_context_review"
        source["context_status_summary"]["context_count"] = 2
        source["context_status_summary"]["context_statuses"].append(
            {
                "context_id": "declared-environment-unrelated-9999",
                "family": "declared_environment",
                "label": "Unrelated declared environment",
                "record_status": "review_needed",
                "authority": "declared_environment_summary",
                "payload_handling": "family_owned_summary_only",
                "declared_summary": {"manager": "uv"},
                "status_fact_count": 1,
                "severity_counts": {"block": 1},
                "dimension_counts": {"validity": 1},
                "classification": "blocked_for_context_review",
            }
        )
        source["context_status_summary"]["status_findings"].append(
            {
                "context_id": "declared-environment-unrelated-9999",
                "family": "declared_environment",
                "fact_id": "unrelated-env-block-9999",
                "dimension": "validity",
                "state": "invalid",
                "severity": "block",
                "finding": "context_validity_invalid",
                "basis": "This environment belongs to another measurement review.",
                "required_for_current_review": True,
                "does_not_claim": "runnable_readiness",
            }
        )
        source["running_evidence_update_summary"]["evidence_findings"] = []

        summary = build_post_run_review_bundle_summary(source)

        self.assertEqual(summary["classification"], "post_run_review_needs_attention")
        self.assertEqual(
            summary["review_sections"]["status"]["overall_classification"],
            "attention_needed_for_context_review",
        )
        self.assertEqual(summary["review_sections"]["status"]["context_count"], 1)
        self.assertEqual(summary["review_finding_count"], 1)
        self.assertEqual(
            summary["review_findings"][0]["context_id"],
            "parameter-state-rabi-accepted-0042",
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_post_run_review_bundle_summary(source)

        source["completed_measurement"]["label"] = "mutated"
        source["running_evidence_update_summary"]["evidence_refs"][0]["declared_reference"][
            "value"
        ] = "mutated"

        self.assertEqual(summary["completed_measurement"]["label"], "Completed Rabi measurement")
        self.assertEqual(
            summary["review_sections"]["supporting_evidence"]["evidence_refs"][0][
                "declared_reference"
            ]["value"],
            "artifacts/rabi-run-stderr-excerpt.txt",
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["post_run_review_policy"]["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            build_post_run_review_bundle_summary(source)

        source = _load_input()
        source["post_run_review_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_post_run_review_bundle_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["post_run_review_policy"]["review_gui"] = "enabled"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_post_run_review_bundle_summary(source)

    def test_completed_measurement_shape_and_state_are_validated(self) -> None:
        source = _load_input()
        source["completed_measurement"]["storage_path"] = "records/measurement-rabi-0042"

        with self.assertRaisesRegex(ValueError, "completed measurement"):
            build_post_run_review_bundle_summary(source)

        source = _load_input()
        source["completed_measurement"]["completion_state"] = "recording"

        with self.assertRaisesRegex(ValueError, "completion_state"):
            build_post_run_review_bundle_summary(source)

    def test_context_link_summary_must_reference_completed_measurement(self) -> None:
        source = _load_input()
        source["context_link_summary"]["measurement_records"][0]["measurement_record_id"] = (
            "other-measurement"
        )

        with self.assertRaisesRegex(ValueError, "completed measurement"):
            build_post_run_review_bundle_summary(source)

    def test_context_link_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["context_link_summary"]["context_link_policy"]["context_import"] = "performed"

        with self.assertRaisesRegex(ValueError, "context import"):
            build_post_run_review_bundle_summary(source)

    def test_context_status_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["context_status_summary"]["context_status_policy"]["hardware_readiness_check"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "hardware_readiness_check"):
            build_post_run_review_bundle_summary(source)

    def test_running_evidence_update_must_match_source_running_measurement(self) -> None:
        source = _load_input()
        source["running_evidence_update_summary"]["running_record"]["measurement_id"] = (
            "other-running-measurement"
        )

        with self.assertRaisesRegex(ValueError, "source running measurement"):
            build_post_run_review_bundle_summary(source)

    def test_running_evidence_update_boundaries_are_enforced(self) -> None:
        source = _load_input()
        source["running_evidence_update_summary"]["evidence_update_policy"]["payload_import"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "payload_import"):
            build_post_run_review_bundle_summary(source)

        source = _load_input()
        source["running_evidence_update_summary"]["evidence_update_policy"][
            "artifact_provenance"
        ] = "validated"

        with self.assertRaisesRegex(ValueError, "artifact_provenance"):
            build_post_run_review_bundle_summary(source)

    def test_raw_summary_aliasing_is_avoided_for_review_sections(self) -> None:
        source = _load_input()
        original_ref = copy.deepcopy(source["context_link_summary"]["linked_context_refs"][0])
        summary = build_post_run_review_bundle_summary(source)

        source["context_link_summary"]["linked_context_refs"][0]["context_label"] = "mutated"

        self.assertEqual(
            summary["review_sections"]["context"]["linked_context_refs"][0],
            original_ref,
        )


if __name__ == "__main__":
    unittest.main()
