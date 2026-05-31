from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.legacy_locator_sufficiency_review import (
    build_legacy_locator_sufficiency_review_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_locator_sufficiency_review" / "basic_review"


def _load_input() -> dict:
    return json.loads((FIXTURE / "legacy-locator-review-input.json").read_text(encoding="utf-8"))


class LegacyLocatorSufficiencyReviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_legacy_locator_sufficiency_review_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-legacy-locator-review-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("summary_policy", summary)

    def test_reviews_measurement_and_primary_data_locators(self) -> None:
        summary = build_legacy_locator_sufficiency_review_summary(_load_input())
        targets = {target["target_type"]: target for target in summary["targets"]}

        self.assertEqual(summary["classification"], "legacy_locator_review_ready")
        self.assertEqual(summary["target_count"], 2)
        self.assertEqual(
            targets["measurement_legacy_source"]["available_locator_kinds"],
            ["legacy_path", "legacy_record_id"],
        )
        self.assertEqual(
            targets["primary_data_legacy_source"]["classification"],
            "locator_declared_sufficient_for_review",
        )

    def test_operator_note_only_locator_is_insufficient_for_review(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"] = [
            {
                "locator_id": "source-locator-note-0001",
                "kind": "operator_note",
                "display": "Ask the shift lead which legacy record was used.",
                "authority": "operator_declared",
                "reference_state": "declared_available",
            }
        ]

        summary = build_legacy_locator_sufficiency_review_summary(source)
        measurement_target = summary["targets"][0]
        finding = summary["locator_findings"][0]

        self.assertEqual(summary["classification"], "legacy_locator_review_insufficient")
        self.assertEqual(
            measurement_target["classification"],
            "locator_insufficient_operator_note_only",
        )
        self.assertEqual(finding["code"], "legacy_locator_operator_note_only")
        self.assertEqual(finding["does_not_claim"], "legacy_record_missing")

    def test_unavailable_locator_target_is_review_unavailable(self) -> None:
        source = _load_input()
        locator = source["legacy_run_sidecar_summary"]["primary_data_refs"][0][
            "legacy_source_locators"
        ][0]
        locator["reference_state"] = "unavailable"
        locator["reason"] = "The operator has not declared the legacy location yet."

        summary = build_legacy_locator_sufficiency_review_summary(source)
        primary_target = summary["targets"][1]
        finding = summary["locator_findings"][0]

        self.assertEqual(summary["classification"], "legacy_locator_review_unavailable")
        self.assertEqual(primary_target["classification"], "locator_unavailable_for_review")
        self.assertEqual(finding["code"], "legacy_locator_unavailable")
        self.assertEqual(finding["does_not_claim"], "legacy_record_missing_or_deleted")

    def test_unavailable_alternative_is_finding_but_still_reviewable(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"].append(
            {
                "locator_id": "source-locator-uri-0001",
                "kind": "legacy_uri",
                "display": "legacy://session-0001/record-0001",
                "authority": "operator_declared",
                "reference_state": "unavailable",
                "reason": "The legacy URI resolver was not available during review.",
            }
        )

        summary = build_legacy_locator_sufficiency_review_summary(source)
        measurement_target = summary["targets"][0]
        finding = summary["locator_findings"][0]

        self.assertEqual(summary["classification"], "legacy_locator_review_ready_with_findings")
        self.assertEqual(
            measurement_target["classification"],
            "locator_declared_with_unavailable_alternative",
        )
        self.assertEqual(finding["code"], "legacy_locator_alternative_unavailable")
        self.assertEqual(finding["does_not_claim"], "backend_lookup_or_reference_repair")

    def test_positive_backend_lookup_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_review_policy"]["backend_lookup"] = "performed"

        with self.assertRaisesRegex(ValueError, "backend_lookup"):
            build_legacy_locator_sufficiency_review_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["locator_review_policy"]["locator_parser"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_legacy_locator_sufficiency_review_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_legacy_locator_sufficiency_review_summary(source)

        source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"][0][
            "display"
        ] = "mutated"

        self.assertEqual(
            summary["targets"][0]["locators"][0]["display"],
            "legacy-session-0001/record-0001",
        )

    def test_duplicate_locator_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(
            source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"][0]
        )
        source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"].append(
            duplicate
        )

        with self.assertRaisesRegex(ValueError, "duplicate locator_id"):
            build_legacy_locator_sufficiency_review_summary(source)

    def test_available_locator_must_not_carry_reason(self) -> None:
        source = _load_input()
        source["legacy_run_sidecar_summary"]["measurement_record"]["legacy_source_locators"][0][
            "reason"
        ] = "extra"

        with self.assertRaisesRegex(ValueError, "available locator"):
            build_legacy_locator_sufficiency_review_summary(source)

    def test_boundary_output_keeps_lookup_import_and_repair_out_of_scope(self) -> None:
        expected = json.loads(
            (FIXTURE / "expected-legacy-locator-review-summary.json").read_text(encoding="utf-8")
        )
        candidate = expected["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("not backend lookup", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["locator_review_policy"]["path_parsing"], "not_performed")
        self.assertEqual(
            candidate["locator_review_policy"]["legacy_import_acceptance"], "not_performed"
        )
        self.assertEqual(
            attention["locator_values_not_parsed"]["does_not_claim"],
            "backend_reference_validation",
        )
        self.assertIn("reference repair", " ".join(expected["decisions_not_earned"]))


if __name__ == "__main__":
    unittest.main()
