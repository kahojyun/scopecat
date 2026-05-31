from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.reviewed_legacy_sidecar_append_intent import (
    build_reviewed_legacy_sidecar_append_intent_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reviewed_legacy_sidecar_append_intent" / "basic_intent"


def _load_input() -> dict:
    return json.loads((FIXTURE / "append-intent-input.json").read_text(encoding="utf-8"))


class ReviewedLegacySidecarAppendIntentSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_reviewed_legacy_sidecar_append_intent_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-append-intent-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)
        self.assertNotIn("reference_semantics", summary)

    def test_ready_intent_selects_review_debug_evidence_only(self) -> None:
        summary = build_reviewed_legacy_sidecar_append_intent_summary(_load_input())
        evidence = summary["planned_review_evidence"]["legacy_locator_observation_review"]

        self.assertEqual(summary["classification"], "reviewed_legacy_sidecar_append_intent_ready")
        self.assertEqual(summary["append_intent"]["approval_state"], "approved")
        self.assertEqual(evidence["fact_posture"], "review_debug_evidence")
        self.assertEqual(evidence["locator_observation_count"], 1)
        self.assertEqual(evidence["does_not_claim"], "primary_data_import_or_preview_verification")
        self.assertFalse(summary["append_intent"]["include_primary_data"])
        self.assertFalse(summary["append_intent"]["include_legacy_payloads"])

    def test_intent_effects_do_not_write_import_repair_or_claim_validity(self) -> None:
        summary = build_reviewed_legacy_sidecar_append_intent_summary(_load_input())
        effects = summary["intent_effects"]

        self.assertEqual(effects["storage_mutation"], "not_performed")
        self.assertEqual(effects["record_write"], "not_performed")
        self.assertEqual(effects["primary_data_import"], "not_performed")
        self.assertEqual(effects["reference_repair"], "not_performed")
        self.assertEqual(effects["parameter_write_back"], "not_performed")
        self.assertEqual(effects["measurement_validity"], "not_claimed")

    def test_source_review_findings_make_intent_ready_with_findings(self) -> None:
        source = _load_input()
        review = source["legacy_locator_observation_review_bundle_summary"]
        review["classification"] = "legacy_locator_observation_review_has_file_fact_mismatch"
        review["review_findings"] = [
            {
                "code": "legacy_locator_source_digest_mismatch",
                "severity": "review",
                "source_section": "legacy_locator_observation",
                "target_id": "primary-legacy-table-0001",
                "locator_id": "primary-locator-path-0001",
                "basis": "Observed sha256 digest differs from declared facts.",
                "does_not_claim": "cause_attribution_or_data_parsing",
            }
        ]
        review["review_finding_count"] = 1

        summary = build_reviewed_legacy_sidecar_append_intent_summary(source)

        self.assertEqual(
            summary["classification"],
            "reviewed_legacy_sidecar_append_intent_ready_with_review_findings",
        )
        self.assertEqual(summary["source_review"]["review_finding_count"], 1)
        self.assertEqual(summary["review_findings"][0]["locator_id"], "primary-locator-path-0001")

    def test_requires_explicit_operator_approval(self) -> None:
        source = _load_input()
        source["append_request"]["operator_approval"]["approval_state"] = "deferred"

        with self.assertRaisesRegex(ValueError, "approved operator approval"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_request_measurement_must_match_source_review(self) -> None:
        source = _load_input()
        source["append_request"]["measurement_id"] = "other-measurement"

        with self.assertRaisesRegex(ValueError, "measurement_id"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_request_must_not_include_primary_payload_repair_or_validity(self) -> None:
        cases = [
            ("include_primary_data", True, "primary data"),
            ("include_legacy_payloads", True, "legacy payloads"),
            ("include_reference_repair", True, "reference repair"),
            ("include_measurement_validity", True, "measurement validity"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                source = _load_input()
                source["append_request"][field] = value

                with self.assertRaisesRegex(ValueError, message):
                    build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_request_must_select_expected_fact_sets(self) -> None:
        source = _load_input()
        source["append_request"]["selected_fact_sets"] = ["sidecar_post_run_review"]

        with self.assertRaisesRegex(ValueError, "fact sets"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_append_destination_stays_intent_only(self) -> None:
        source = _load_input()
        source["append_request"]["append_destination"]["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

        source = _load_input()
        source["append_request"]["append_destination"]["append_posture"] = "write_now"

        with self.assertRaisesRegex(ValueError, "intent_only"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["append_intent_policy"]["storage_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "storage_mutation"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

        source = _load_input()
        source["append_intent_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["append_intent_policy"]["record_append"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_source_review_policy_must_stay_non_mutating(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_review_bundle_summary"][
            "locator_observation_review_policy"
        ]["record_write"] = "performed"

        with self.assertRaisesRegex(ValueError, "record_write"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_source_review_finding_count_is_validated(self) -> None:
        source = _load_input()
        source["legacy_locator_observation_review_bundle_summary"]["review_finding_count"] = 9

        with self.assertRaisesRegex(ValueError, "review_finding_count"):
            build_reviewed_legacy_sidecar_append_intent_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        source_copy = copy.deepcopy(source)
        summary = build_reviewed_legacy_sidecar_append_intent_summary(source)

        source["append_request"]["append_destination"]["record_write"] = "performed"
        source["legacy_locator_observation_review_bundle_summary"]["review_sections"][
            "legacy_locator_observation"
        ]["classification_counts"]["mutated"] = 1

        self.assertEqual(
            summary["append_intent"]["append_destination"]["record_write"], "not_performed"
        )
        self.assertEqual(
            summary["planned_review_evidence"]["legacy_locator_observation_review"][
                "classification_counts"
            ],
            source_copy["legacy_locator_observation_review_bundle_summary"]["review_sections"][
                "legacy_locator_observation"
            ]["classification_counts"],
        )

    def test_boundary_output_keeps_append_import_repair_and_validity_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-append-intent-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("approved intent", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["intent_effects"]["record_write"], "not_performed")
        self.assertEqual(candidate["intent_effects"]["primary_data_import"], "not_performed")
        self.assertEqual(candidate["intent_effects"]["reference_repair"], "not_performed")
        self.assertEqual(candidate["intent_effects"]["measurement_validity"], "not_claimed")
        self.assertEqual(
            attention["append_intent_only"]["does_not_claim"],
            "durable_record_update",
        )
        self.assertIn("durable measurement-record append", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
