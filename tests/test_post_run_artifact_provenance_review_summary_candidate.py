from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.post_run_artifact_provenance_review import (
    build_post_run_artifact_provenance_review_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "post_run_artifact_provenance_review" / "basic_review"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-input.json").read_text(encoding="utf-8"))


class PostRunArtifactProvenanceReviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_post_run_artifact_provenance_review_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_provenance_findings_are_carried_without_validity_claims(self) -> None:
        summary = build_post_run_artifact_provenance_review_summary(_load_input())
        findings = summary["review_findings"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["classification"],
            "post_run_artifact_provenance_review_needs_attention",
        )
        self.assertEqual(summary["review_finding_count"], 2)
        self.assertEqual(
            {finding["source_section"] for finding in findings},
            {"context_status", "artifact_provenance"},
        )
        self.assertEqual(
            attention["validity_not_claimed"]["does_not_claim"],
            "artifact_or_measurement_validity",
        )

    def test_artifact_and_source_payloads_are_not_observed(self) -> None:
        summary = build_post_run_artifact_provenance_review_summary(_load_input())
        policy = summary["artifact_provenance_review_policy"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(policy["artifact_file_observation"], "not_performed")
        self.assertEqual(policy["source_payload_observation"], "not_performed")
        self.assertEqual(policy["checksum_validation"], "not_performed")
        self.assertEqual(
            attention["artifact_and_sources_not_observed"]["does_not_claim"],
            "artifact_or_source_integrity_verified",
        )

    def test_ready_classification_when_base_and_provenance_have_no_findings(self) -> None:
        source = _load_input()
        source["post_run_review_summary"]["classification"] = "post_run_review_ready"
        source["post_run_review_summary"]["review_finding_count"] = 0
        source["post_run_review_summary"]["review_findings"] = []
        summary = source["artifact_provenance_summaries"][0]
        summary["classification"] = "ready_for_artifact_provenance_review"
        summary["source_state_counts"] = {"declared_available": 3}
        summary["source_links"][2]["source_state"] = "declared_available"
        summary["source_links"][2]["reason"] = None
        summary["provenance_finding_count"] = 0
        summary["provenance_findings"] = []

        output = build_post_run_artifact_provenance_review_summary(source)

        self.assertEqual(output["classification"], "post_run_artifact_provenance_review_ready")
        self.assertEqual(output["review_findings"], [])

    def test_blocked_classification_follows_base_post_run_review(self) -> None:
        source = _load_input()
        source["post_run_review_summary"]["classification"] = (
            "post_run_review_blocked_for_context_review"
        )

        output = build_post_run_artifact_provenance_review_summary(source)

        self.assertEqual(
            output["classification"],
            "post_run_artifact_provenance_review_blocked",
        )

    def test_empty_artifact_provenance_list_is_allowed(self) -> None:
        source = _load_input()
        source["post_run_review_summary"]["classification"] = "post_run_review_ready"
        source["post_run_review_summary"]["review_finding_count"] = 0
        source["post_run_review_summary"]["review_findings"] = []
        source["artifact_provenance_summaries"] = []

        output = build_post_run_artifact_provenance_review_summary(source)

        self.assertEqual(output["classification"], "post_run_artifact_provenance_review_ready")
        self.assertEqual(
            output["review_sections"]["artifact_provenance"]["artifact_provenance_count"],
            0,
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        original_link = copy.deepcopy(source["artifact_provenance_summaries"][0]["source_links"][0])
        summary = build_post_run_artifact_provenance_review_summary(source)

        source["post_run_review_summary"]["completed_measurement"]["label"] = "mutated"
        source["artifact_provenance_summaries"][0]["source_links"][0]["label"] = "mutated"

        self.assertEqual(summary["completed_measurement"]["label"], "Completed Rabi measurement")
        self.assertEqual(
            summary["review_sections"]["artifact_provenance"]["artifacts"][0]["source_links"][0],
            original_link,
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_provenance_review_policy"]["artifact_file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_file_observation"):
            build_post_run_artifact_provenance_review_summary(source)

        source = _load_input()
        source["artifact_provenance_review_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_provenance_review_policy"]["artifact_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_base_post_run_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["post_run_review_summary"]["post_run_review_policy"]["primary_data_observation"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "primary_data_observation"):
            build_post_run_artifact_provenance_review_summary(source)

        source = _load_input()
        source["post_run_review_summary"]["post_run_review_policy"]["artifact_provenance"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "artifact_provenance"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_artifact_provenance_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["artifact_provenance_summaries"][0]["artifact_provenance_policy"][
            "artifact_file_observation"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_file_observation"):
            build_post_run_artifact_provenance_review_summary(source)

        source = _load_input()
        source["artifact_provenance_summaries"][0]["artifact_provenance_policy"][
            "analysis_dag_inference"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "analysis_dag_inference"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_provenance_must_match_post_run_artifact_evidence(self) -> None:
        source = _load_input()
        source["artifact_provenance_summaries"][0]["artifact"]["artifact_id"] = "missing-artifact"

        with self.assertRaisesRegex(ValueError, "post-run artifact evidence"):
            build_post_run_artifact_provenance_review_summary(source)

        source = _load_input()
        source["artifact_provenance_summaries"][0]["artifact"]["declared_reference"]["value"] = (
            "artifacts/other.json"
        )

        with self.assertRaisesRegex(ValueError, "declared reference"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_duplicate_artifact_provenance_summaries_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_provenance_summaries"].append(
            copy.deepcopy(source["artifact_provenance_summaries"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate artifact provenance summary"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_provenance_must_link_to_completed_measurement(self) -> None:
        source = _load_input()
        source["artifact_provenance_summaries"][0]["source_links"][0]["source_id"] = (
            "other-measurement"
        )

        with self.assertRaisesRegex(ValueError, "completed measurement"):
            build_post_run_artifact_provenance_review_summary(source)

    def test_duplicate_artifact_evidence_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(
            source["post_run_review_summary"]["review_sections"]["supporting_evidence"][
                "evidence_refs"
            ][1]
        )
        source["post_run_review_summary"]["review_sections"]["supporting_evidence"][
            "evidence_refs"
        ].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate artifact evidence_id"):
            build_post_run_artifact_provenance_review_summary(source)


if __name__ == "__main__":
    unittest.main()
