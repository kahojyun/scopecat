from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.resolved_context_link_comparison import (
    build_resolved_context_link_comparison_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "resolved_context_link_comparison" / "basic_selected_reference"
)

FINDING_CODES = [
    "changed_parameter_state",
    "same_observed_setup_binding",
    "same_observed_managed_code_version",
    "missing_current_declared_environment_context",
]


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "resolved-context-comparison-input.json").read_text(encoding="utf-8")
    )


class ResolvedContextLinkComparisonSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_resolved_context_link_comparison_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-resolved-context-comparison-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_compares_resolved_links_not_intent_selectors(self) -> None:
        summary = build_resolved_context_link_comparison_summary(_load_input())
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(
            summary["context_link_comparison"][0]["reference_context_id"],
            "param-state-0007",
        )
        self.assertEqual(
            summary["context_link_comparison"][0]["current_context_id"],
            "param-state-0008",
        )
        self.assertIn("measurement_intent_selectors", summary["not_compared_scope"])
        self.assertEqual(
            attention["resolved_links_only"]["does_not_claim"],
            "intent_selector_comparison",
        )

    def test_reports_objective_context_findings_without_cause_attribution(self) -> None:
        summary = build_resolved_context_link_comparison_summary(_load_input())
        findings = {item["code"]: item for item in summary["findings"]}
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual([item["code"] for item in summary["findings"]], FINDING_CODES)
        self.assertEqual(findings["changed_parameter_state"]["kind"], "changed")
        self.assertEqual(findings["same_observed_setup_binding"]["kind"], "same_observed")
        self.assertEqual(
            findings["missing_current_declared_environment_context"]["kind"],
            "missing",
        )
        self.assertEqual(
            attention["cause_attribution_not_performed"]["does_not_claim"],
            "reason_measurement_changed",
        )

    def test_keeps_payloads_primary_data_and_readiness_out_of_scope(self) -> None:
        summary = build_resolved_context_link_comparison_summary(_load_input())
        not_compared = summary["not_compared_scope"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertIn("primary_measurement_data", not_compared)
        self.assertIn("fit_quality", not_compared)
        self.assertIn("context_payloads", not_compared)
        self.assertIn("readiness_or_run_blocking", not_compared)
        self.assertEqual(
            attention["context_payloads_not_compared"]["does_not_claim"],
            "semantic_payload_diff",
        )
        self.assertEqual(
            attention["primary_data_not_compared"]["does_not_claim"],
            "scientific_outcome_comparison",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["comparison_policy"]["cause_attribution"] = "performed"

        with self.assertRaisesRegex(ValueError, "cause_attribution"):
            build_resolved_context_link_comparison_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["comparison_policy"]["raw_plot_overlay"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_resolved_context_link_comparison_summary(source)

    def test_scope_expansion_to_intent_selectors_is_rejected(self) -> None:
        source = _load_input()
        source["comparison_request"]["comparison_scope"].append("measurement_intent_selectors")

        with self.assertRaisesRegex(ValueError, "comparison scope"):
            build_resolved_context_link_comparison_summary(source)

    def test_special_reference_selection_semantics_are_rejected(self) -> None:
        source = _load_input()
        source["comparison_request"]["reference_selection"]["selection_source"] = (
            "scopecat_reference_engine"
        )

        with self.assertRaisesRegex(ValueError, "ordinary measurement marks"):
            build_resolved_context_link_comparison_summary(source)

    def test_context_links_must_remain_optional_for_record_validity(self) -> None:
        source = _load_input()
        source["measurements"][0]["context_links"][0]["required_for_record_validity"] = True

        with self.assertRaisesRegex(ValueError, "optional for measurement record"):
            build_resolved_context_link_comparison_summary(source)

    def test_reference_and_current_link_keys_must_match(self) -> None:
        source = _load_input()
        source["measurements"][1]["context_links"].pop()

        with self.assertRaisesRegex(ValueError, "keys must match"):
            build_resolved_context_link_comparison_summary(source)

    def test_linked_context_must_reference_known_context_record(self) -> None:
        source = _load_input()
        source["measurements"][0]["context_links"][0]["context_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing context"):
            build_resolved_context_link_comparison_summary(source)

    def test_linked_context_family_must_match(self) -> None:
        source = _load_input()
        source["measurements"][0]["context_links"][0]["context_id"] = "setup-binding-0002"

        with self.assertRaisesRegex(ValueError, "wrong family"):
            build_resolved_context_link_comparison_summary(source)

    def test_unavailable_optional_context_requires_reason(self) -> None:
        source = _load_input()
        source["measurements"][1]["context_links"][-1].pop("missing_reason")

        with self.assertRaisesRegex(ValueError, "missing_reason"):
            build_resolved_context_link_comparison_summary(source)

    def test_duplicate_link_ids_within_measurement_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["measurements"][0]["context_links"][0])
        source["measurements"][0]["context_links"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate link_id"):
            build_resolved_context_link_comparison_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_resolved_context_link_comparison_summary(source)

        source["comparison_request"]["not_compared_scope"][0] = "mutated"
        source["measurements"][0]["context_links"][0]["context_id"] = "mutated"

        self.assertEqual(summary["not_compared_scope"][0], "measurement_intent_selectors")
        self.assertEqual(
            summary["context_link_comparison"][0]["reference_context_id"],
            "param-state-0007",
        )


if __name__ == "__main__":
    unittest.main()
