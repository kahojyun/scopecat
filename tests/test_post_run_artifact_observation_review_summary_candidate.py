from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.post_run_artifact_observation_review import (
    build_post_run_artifact_observation_review_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "post_run_artifact_observation_review" / "basic_review"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-input.json").read_text(encoding="utf-8"))


class PostRunArtifactObservationReviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_post_run_artifact_observation_review_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_observation_findings_are_carried_without_validity_claims(self) -> None:
        summary = build_post_run_artifact_observation_review_summary(_load_input())
        findings = summary["review_findings"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["classification"],
            "post_run_artifact_observation_review_needs_attention",
        )
        self.assertEqual(summary["review_finding_count"], 2)
        self.assertEqual(
            {finding["source_section"] for finding in findings},
            {"artifact_provenance", "artifact_observation"},
        )
        self.assertEqual(
            attention["validity_not_claimed"]["does_not_claim"],
            "artifact_or_measurement_validity",
        )

    def test_no_fresh_observation_or_payload_parsing_is_claimed(self) -> None:
        summary = build_post_run_artifact_observation_review_summary(_load_input())
        policy = summary["artifact_observation_review_policy"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(policy["fresh_artifact_file_observation"], "not_performed")
        self.assertEqual(policy["fresh_checksum_validation"], "not_performed")
        self.assertEqual(policy["artifact_parsing"], "not_performed")
        self.assertEqual(policy["preview_generation"], "not_performed")
        self.assertEqual(
            attention["artifact_observation_is_prior_summary"]["does_not_claim"],
            "fresh_artifact_file_observation",
        )

    def test_ready_classification_when_base_and_observations_are_ready(self) -> None:
        source = _load_input()
        source["post_run_artifact_provenance_review_summary"]["classification"] = (
            "post_run_artifact_provenance_review_ready"
        )
        source["post_run_artifact_provenance_review_summary"]["review_finding_count"] = 0
        source["post_run_artifact_provenance_review_summary"]["review_findings"] = []
        observation = source["artifact_observation_summaries"][0]
        observation["artifact"]["classification"] = (
            "supporting_artifact_observed_matches_declared_file_facts"
        )
        observation["review_findings"] = []

        summary = build_post_run_artifact_observation_review_summary(source)

        self.assertEqual(summary["classification"], "post_run_artifact_observation_review_ready")
        self.assertEqual(summary["review_findings"], [])

    def test_blocked_classification_follows_base_post_run_review(self) -> None:
        source = _load_input()
        source["post_run_artifact_provenance_review_summary"]["classification"] = (
            "post_run_artifact_provenance_review_blocked"
        )

        summary = build_post_run_artifact_observation_review_summary(source)

        self.assertEqual(
            summary["classification"],
            "post_run_artifact_observation_review_blocked",
        )

    def test_empty_observation_list_is_allowed(self) -> None:
        source = _load_input()
        source["post_run_artifact_provenance_review_summary"]["classification"] = (
            "post_run_artifact_provenance_review_ready"
        )
        source["post_run_artifact_provenance_review_summary"]["review_finding_count"] = 0
        source["post_run_artifact_provenance_review_summary"]["review_findings"] = []
        source["artifact_observation_summaries"] = []

        summary = build_post_run_artifact_observation_review_summary(source)

        self.assertEqual(summary["classification"], "post_run_artifact_observation_review_ready")
        self.assertEqual(
            summary["review_sections"]["artifact_observation"]["artifact_observation_count"],
            0,
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        original_observed = copy.deepcopy(
            source["artifact_observation_summaries"][0]["observed_artifact"]
        )
        summary = build_post_run_artifact_observation_review_summary(source)

        source["post_run_artifact_provenance_review_summary"]["completed_measurement"]["label"] = (
            "mutated"
        )
        source["artifact_observation_summaries"][0]["observed_artifact"]["path"] = "mutated"

        self.assertEqual(summary["completed_measurement"]["label"], "Completed Rabi measurement")
        self.assertEqual(
            summary["review_sections"]["artifact_observation"]["artifacts"][0]["observed_artifact"],
            original_observed,
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_observation_review_policy"]["fresh_artifact_file_observation"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "fresh_artifact_file_observation"):
            build_post_run_artifact_observation_review_summary(source)

        source = _load_input()
        source["artifact_observation_review_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_post_run_artifact_observation_review_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_observation_review_policy"]["artifact_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_post_run_artifact_observation_review_summary(source)

    def test_base_post_run_provenance_review_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["post_run_artifact_provenance_review_summary"]["artifact_provenance_review_policy"][
            "checksum_validation"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "checksum_validation"):
            build_post_run_artifact_observation_review_summary(source)

    def test_artifact_observation_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["artifact_observation_summaries"][0]["artifact_observation_policy"][
            "artifact_parsing"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_parsing"):
            build_post_run_artifact_observation_review_summary(source)

        source = _load_input()
        source["artifact_observation_summaries"][0]["artifact_observation_policy"][
            "source_payload_observation"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "source_payload_observation"):
            build_post_run_artifact_observation_review_summary(source)

    def test_observation_must_match_reviewed_artifact(self) -> None:
        source = _load_input()
        source["artifact_observation_summaries"][0]["artifact"]["artifact_id"] = "missing-artifact"

        with self.assertRaisesRegex(ValueError, "reviewed artifact"):
            build_post_run_artifact_observation_review_summary(source)

        source = _load_input()
        source["artifact_observation_summaries"][0]["artifact"]["declared_reference"]["value"] = (
            "artifacts/other.json"
        )

        with self.assertRaisesRegex(ValueError, "declared reference"):
            build_post_run_artifact_observation_review_summary(source)

    def test_observed_artifact_must_match_observation_artifact(self) -> None:
        source = _load_input()
        source["artifact_observation_summaries"][0]["observed_artifact"]["artifact_id"] = (
            "other-artifact"
        )

        with self.assertRaisesRegex(ValueError, "observed artifact_id"):
            build_post_run_artifact_observation_review_summary(source)

        source = _load_input()
        source["artifact_observation_summaries"][0]["observed_artifact"]["path"] = (
            "artifacts/other.json"
        )

        with self.assertRaisesRegex(ValueError, "observed artifact path"):
            build_post_run_artifact_observation_review_summary(source)

    def test_duplicate_observation_summaries_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_observation_summaries"].append(
            copy.deepcopy(source["artifact_observation_summaries"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate artifact observation summary"):
            build_post_run_artifact_observation_review_summary(source)

    def test_duplicate_reviewed_artifacts_are_rejected(self) -> None:
        source = _load_input()
        artifacts = source["post_run_artifact_provenance_review_summary"]["review_sections"][
            "artifact_provenance"
        ]["artifacts"]
        artifacts.append(copy.deepcopy(artifacts[0]))

        with self.assertRaisesRegex(ValueError, "duplicate reviewed artifact_id"):
            build_post_run_artifact_observation_review_summary(source)


if __name__ == "__main__":
    unittest.main()
