from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_locator_observation_review_bundle import (
    build_legacy_locator_observation_review_bundle_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_locator_observation_review_bundle" / "basic_bundle"


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "locator-observation-review-bundle-input.json").read_text(encoding="utf-8")
    )


class LegacyLocatorObservationReviewBundleSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_legacy_locator_observation_review_bundle_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-locator-observation-review-bundle-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)
        self.assertNotIn("reference_semantics", summary)

    def test_ready_bundle_carries_prior_observation_without_fresh_observation(self) -> None:
        summary = build_legacy_locator_observation_review_bundle_summary(_load_input())
        section = summary["review_sections"]["legacy_locator_observation"]
        observation = section["observations"][0]

        self.assertEqual(summary["classification"], "legacy_locator_observation_review_ready")
        self.assertEqual(section["locator_observation_count"], 1)
        self.assertEqual(section["file_backed_locator_count"], 2)
        self.assertEqual(
            section["classification_counts"], {"legacy_file_backed_locator_observed": 1}
        )
        self.assertEqual(observation["observed_legacy_source"]["status"], "observed")
        self.assertEqual(
            observation["declared_preview_assertion"]["verification_state"],
            "not_verified_by_file_level_observation",
        )
        self.assertEqual(
            summary["locator_observation_review_policy"]["fresh_file_observation"],
            "not_performed",
        )

    def test_empty_observations_are_allowed_as_optional_review_state(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_summaries"] = []

        summary = build_legacy_locator_observation_review_bundle_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_locator_observation_review_ready_without_observation",
        )
        self.assertEqual(
            summary["review_sections"]["legacy_locator_observation"]["locator_observation_count"],
            0,
        )
        self.assertEqual(summary["review_finding_count"], 0)

    def test_unavailable_observation_drives_review_classification(self) -> None:
        source = _load_input()
        observation = source["legacy_locator_observation_summaries"][0]
        observation["classification"] = "legacy_file_backed_locator_unavailable_for_review"
        observation["observed_legacy_source"]["status"] = "unavailable"
        observation["observed_legacy_source"]["observed_digest"] = None
        observation["observed_legacy_source"]["observed_size_bytes"] = None
        observation["review_findings"] = [
            {
                "code": "legacy_locator_source_unavailable",
                "severity": "review",
                "basis": "The selected legacy_path locator could not be observed.",
                "does_not_claim": "reference_repair_or_moved_reference_discovery",
            }
        ]

        summary = build_legacy_locator_observation_review_bundle_summary(source)
        finding = summary["review_findings"][0]

        self.assertEqual(
            summary["classification"],
            "legacy_locator_observation_review_has_unavailable_locator",
        )
        self.assertEqual(finding["source_section"], "legacy_locator_observation")
        self.assertEqual(finding["locator_id"], "primary-locator-path-0001")
        self.assertEqual(finding["does_not_claim"], "reference_repair_or_moved_reference_discovery")

    def test_mismatch_observation_drives_file_fact_mismatch_classification(self) -> None:
        source = _load_input()
        observation = source["legacy_locator_observation_summaries"][0]
        observation["classification"] = (
            "legacy_file_backed_locator_observed_with_file_fact_mismatch"
        )
        observation["review_findings"] = [
            {
                "code": "legacy_locator_source_digest_mismatch",
                "severity": "review",
                "basis": "Observed sha256 digest differs from declared facts.",
                "does_not_claim": "cause_attribution_or_data_parsing",
            }
        ]

        summary = build_legacy_locator_observation_review_bundle_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_locator_observation_review_has_file_fact_mismatch",
        )
        self.assertEqual(summary["review_finding_count"], 1)
        self.assertEqual(
            summary["review_sections"]["legacy_locator_observation"]["observation_finding_count"],
            1,
        )

    def test_sidecar_attention_classification_takes_precedence(self) -> None:
        source = _load_input()
        source["legacy_sidecar_post_run_review_summary"]["classification"] = (
            "legacy_sidecar_post_run_needs_locator_review"
        )

        summary = build_legacy_locator_observation_review_bundle_summary(source)

        self.assertEqual(
            summary["classification"],
            "legacy_locator_observation_review_needs_sidecar_attention",
        )

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_observation_review_policy"]["fresh_file_observation"] = "performed"

        with self.assertRaisesRegex(ValueError, "fresh_file_observation"):
            build_legacy_locator_observation_review_bundle_summary(source)

        source = _load_input()
        source["locator_observation_review_policy"]["legacy_import_acceptance"] = "performed"

        with self.assertRaisesRegex(ValueError, "legacy_import_acceptance"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_observation_review_policy"]["durable_append"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_observation_summary_must_match_reviewed_locator(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["selected_locator"]["locator_id"] = (
            "other-locator"
        )

        with self.assertRaisesRegex(ValueError, "reviewed sidecar locator"):
            build_legacy_locator_observation_review_bundle_summary(source)

        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["selected_locator"]["display"] = "mutated"

        with self.assertRaisesRegex(ValueError, "display"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_observation_request_and_observed_source_must_match_selected_locator(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["observation_request"]["target_id"] = (
            "other-target"
        )

        with self.assertRaisesRegex(ValueError, "target_id"):
            build_legacy_locator_observation_review_bundle_summary(source)

        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["observed_legacy_source"]["path"] = (
            "other.csv"
        )

        with self.assertRaisesRegex(ValueError, "path"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_observation_effect_claims_are_rejected(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["observation_effects"][
            "reference_repair"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "reference_repair"):
            build_legacy_locator_observation_review_bundle_summary(source)

        source = _load_input()
        source["legacy_locator_observation_summaries"][0]["observation_effects"][
            "measurement_validity"
        ] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement validity"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_duplicate_observation_summaries_are_rejected(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_summaries"].append(
            copy.deepcopy(source["legacy_locator_observation_summaries"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate locator observation"):
            build_legacy_locator_observation_review_bundle_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_locator_observation_review_bundle_summary(source)

        source["legacy_locator_observation_summaries"][0]["selected_locator"]["display"] = "mutated"
        source["legacy_sidecar_post_run_review_summary"]["review_findings"].append(
            {"code": "mutated"}
        )

        observation = summary["review_sections"]["legacy_locator_observation"]["observations"][0]
        self.assertEqual(
            observation["selected_locator"]["display"],
            "<redacted-legacy-storage-root>/session-0001/record-0001 - measurement.csv",
        )
        self.assertEqual(
            summary["review_sections"]["sidecar_post_run_review"]["review_findings"], []
        )

    def test_boundary_output_keeps_import_repair_and_preview_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-locator-observation-review-bundle-summary.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn(
            "prior locator-observation", expected["reference_semantics"]["contract_guard"]
        )
        self.assertEqual(
            candidate["locator_observation_review_policy"]["fresh_file_observation"],
            "not_performed",
        )
        self.assertEqual(
            candidate["locator_observation_review_policy"]["reference_repair"],
            "not_performed",
        )
        self.assertEqual(
            attention["legacy_payload_not_parsed"]["does_not_claim"],
            "row_count_schema_preview_or_data_validation",
        )
        self.assertIn("durable measurement-record update", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
