from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_review_gate import (
    build_prepared_run_review_gate_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_review_gate" / "basic_gate"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-gate-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-review-gate-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


def _clear_non_parameter_findings(source: dict) -> None:
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    source["prepared_run_context_summary"]["workspace_context_findings"] = []
    source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
    source["scope_alignment_summary"]["review_findings"] = []
    source["environment_review_summary"]["environment_review_findings"] = []


class PreparedRunReviewGateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_review_gate_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_review_gate_summary(source)

        source["prepared_run_context_summary"]["prepared_run_contexts"][0]["label"] = "mutated"
        source["prepared_run_context_summary"]["workspace_context_findings"][0]["basis"][
            "changed_observed"
        ] = 99

        self.assertEqual(summary["prepared_run_context"]["label"], "qA chevron manual run context")
        self.assertEqual(
            summary["aggregated_review_findings"][1]["basis"]["changed_observed"],
            1,
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["review_gate_policy"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_review_gate_summary(source)

    def test_child_summary_must_not_claim_execution(self) -> None:
        source = _load_input()
        source["environment_review_summary"]["environment_review_bundle_policy"][
            "code_import_execution"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "code_import_execution"):
            build_prepared_run_review_gate_summary(source)

    def test_needs_review_without_required_context_block(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["missing_context_findings"] = []

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_scope_review",
            {item["state"] for item in summary["review_items"]},
        )

    def test_prepared_context_findings_are_filtered_to_requested_context(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["missing_context_findings"][0][
            "prepared_run_context_id"
        ] = "prepared-run-context-other"
        source["prepared_run_context_summary"]["workspace_context_findings"][0][
            "prepared_run_context_id"
        ] = "prepared-run-context-other"
        source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
        source["scope_alignment_summary"]["review_findings"] = []
        source["environment_review_summary"]["environment_review_findings"] = []

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "ready_for_manual_review")
        self.assertEqual(summary["aggregated_review_findings"], [])
        self.assertEqual(
            {item["state"] for item in summary["review_items"]},
            {"ready_for_manual_review"},
        )

    def test_ready_when_all_review_areas_are_clear(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "ready_for_manual_review")
        self.assertEqual(summary["aggregated_review_findings"], [])
        self.assertEqual(
            {item["state"] for item in summary["review_items"]},
            {"ready_for_manual_review"},
        )

    def test_parameter_gate_needs_review_is_carried(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)
        source["parameter_state_gate_summary"]["gate_decision"]["gate_state"] = (
            "needs_parameter_review"
        )
        source["parameter_state_gate_summary"]["gate_decision"]["reason_codes"] = [
            "insufficient_trusted_entries"
        ]
        source["parameter_state_gate_summary"]["review_findings"] = [
            {
                "code": "insufficient_trusted_entries",
                "severity": "review",
                "basis": {"required_min_trusted_entries": 3, "trusted_entry_count": 2},
                "does_not_claim": "automatic_parameter_completion_or_write_back",
            }
        ]

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_parameter_review",
            {item["state"] for item in summary["review_items"]},
        )
        self.assertIn(
            "insufficient_trusted_entries",
            {finding["code"] for finding in summary["aggregated_review_findings"]},
        )

    def test_request_must_match_child_prepared_context_ids(self) -> None:
        source = _load_input()
        source["scope_alignment_summary"]["scope_summary"]["prepared_run_context_id"] = (
            "different-context"
        )

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_review_gate_summary(source)


if __name__ == "__main__":
    unittest.main()
