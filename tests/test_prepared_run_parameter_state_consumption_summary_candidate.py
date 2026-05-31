from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_parameter_state_consumption import (
    build_prepared_run_parameter_state_consumption_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "prepared_run_parameter_state_consumption" / "basic_consumption"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "consumption-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-consumption-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


def _parameter_context_ref(source: dict) -> dict:
    for ref in source["prepared_run_context_summary"]["selected_context_refs"]:
        if ref["family"] == "parameter_state" and ref["role"] == "calibrated_values":
            return ref
    raise AssertionError("fixture must include parameter_state calibrated_values ref")


class PreparedRunParameterStateConsumptionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_parameter_state_consumption_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_parameter_state_consumption_summary(source)

        source["parameter_state_read_view_summary"]["trusted_entries"][0]["value"] = "mutated"
        source["prepared_run_context_summary"]["prepared_run_contexts"][0]["label"] = "mutated"

        self.assertEqual(summary["trusted_entries"][0]["value"], 5012500000)
        self.assertEqual(
            summary["prepared_run_context"]["label"],
            "qA chevron manual run context from stored parameter state",
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["consumption_policy"]["fresh_storage_read"] = "performed"

        with self.assertRaisesRegex(ValueError, "fresh_storage_read"):
            build_prepared_run_parameter_state_consumption_summary(source)

    def test_prepared_context_must_not_claim_parameter_write_back(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["prepared_run_context_policy"][
            "parameter_write_back"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_write_back"):
            build_prepared_run_parameter_state_consumption_summary(source)

    def test_read_view_must_not_claim_catalog_discovery(self) -> None:
        source = _load_input()
        source["parameter_state_read_view_summary"]["read_view_policy"]["catalog_discovery"] = (
            "performed"
        )

        with self.assertRaisesRegex(ValueError, "catalog_discovery"):
            build_prepared_run_parameter_state_consumption_summary(source)

    def test_parameter_context_id_mismatch_is_review_finding(self) -> None:
        source = _load_input()
        _parameter_context_ref(source)["context_id"] = "different-state-id"

        summary = build_prepared_run_parameter_state_consumption_summary(source)

        self.assertEqual(summary["classification"], "prepared_run_parameter_state_needs_review")
        self.assertIn(
            "prepared_context_state_id_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_read_view_findings_are_carried_forward(self) -> None:
        source = _load_input()
        source["parameter_state_read_view_summary"]["classification"] = (
            "stored_parameter_state_observed_with_mismatch"
        )
        source["parameter_state_read_view_summary"]["review_findings"] = [
            {
                "code": "manifest_digest_mismatch",
                "severity": "review",
                "basis": "Observed manifest digest differs.",
                "does_not_claim": "repair",
            }
        ]

        summary = build_prepared_run_parameter_state_consumption_summary(source)

        self.assertEqual(summary["classification"], "prepared_run_parameter_state_needs_review")
        self.assertIn(
            "parameter_state_read_view_not_ready",
            {finding["code"] for finding in summary["review_findings"]},
        )
        self.assertIn(
            "parameter_state_read_view_finding",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_unavailable_selected_parameter_context_is_review_finding(self) -> None:
        source = _load_input()
        ref = _parameter_context_ref(source)
        ref["include_state"] = "unavailable"
        ref["context_id"] = None
        ref["missing_reason"] = "No reviewed stored parameter state was selected."

        summary = build_prepared_run_parameter_state_consumption_summary(source)

        self.assertEqual(
            summary["classification"], "prepared_run_parameter_state_unavailable_for_review"
        )
        self.assertIn(
            "prepared_parameter_context_unavailable",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_trusted_entries_must_match_read_view_state(self) -> None:
        source = _load_input()
        source["parameter_state_read_view_summary"]["trusted_entries"].append(
            copy.deepcopy(source["parameter_state_read_view_summary"]["trusted_entries"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate trusted entry"):
            build_prepared_run_parameter_state_consumption_summary(source)


if __name__ == "__main__":
    unittest.main()
