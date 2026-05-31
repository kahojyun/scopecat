from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_acknowledgement_aware_review_gate import (
    build_prepared_run_acknowledgement_aware_review_gate_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "prepared_run_acknowledgement_aware_review_gate" / "basic_ready"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-review-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunAcknowledgementAwareReviewGateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(source)

        source["partial_target_acknowledgement_summary"]["prepared_run_context"][
            "logical_targets"
        ].append("mutated")
        source["partial_target_acknowledgement_summary"]["acknowledged_finding"]["basis"][
            "missing_targets"
        ].append("mutated")

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(
            summary["acknowledged_review_findings"][0]["basis"],
            {"covered_targets": ["qA"], "missing_targets": ["cAB"]},
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["acknowledgement_aware_review_policy"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_acknowledgement_aware_review_gate_summary(source)

    def test_acknowledgement_must_not_claim_side_effects(self) -> None:
        source = _load_input()
        source["partial_target_acknowledgement_summary"]["side_effects"]["compatibility_output"] = (
            "produced"
        )

        with self.assertRaisesRegex(ValueError, "compatibility_output"):
            build_prepared_run_acknowledgement_aware_review_gate_summary(source)

    def test_request_must_match_acknowledgement_context(self) -> None:
        source = _load_input()
        source["review_request"]["prepared_run_context_id"] = "other-context"

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_acknowledgement_aware_review_gate_summary(source)

    def test_request_must_match_acknowledgement_parameter_state(self) -> None:
        source = _load_input()
        source["review_request"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter_state_id"):
            build_prepared_run_acknowledgement_aware_review_gate_summary(source)

    def test_remaining_acknowledgement_finding_keeps_review_needed(self) -> None:
        source = _load_input()
        source["partial_target_acknowledgement_summary"]["remaining_review_findings"] = [
            {
                "source": "parameter_gate",
                "code": "manual_parameter_context_note",
                "severity": "review",
                "basis": {"note": "synthetic review note"},
                "does_not_claim": "run_blocking",
            }
        ]
        source["partial_target_acknowledgement_summary"]["classification"] = (
            "manual_pre_run_review_still_needs_review"
        )

        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_acknowledgement_review",
            {item["state"] for item in summary["review_items"]},
        )
        self.assertEqual(
            summary["remaining_acknowledgement_findings"][0]["code"],
            "manual_parameter_context_note",
        )

    def test_blocked_acknowledgement_blocks_review(self) -> None:
        source = _load_input()
        source["partial_target_acknowledgement_summary"]["classification"] = (
            "partial_target_coverage_acknowledgement_blocked"
        )

        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(source)

        self.assertEqual(
            summary["gate_decision"]["overall_state"],
            "blocked_by_acknowledgement_review",
        )

    def test_required_context_finding_still_blocks(self) -> None:
        source = _load_input()
        source["review_area_inputs"]["required_context_findings"] = [
            {
                "prepared_run_context_id": "prepared-run-context-chevron-qA-0001",
                "code": "required_context_unavailable",
                "severity": "review",
                "basis": "No reviewed declared environment record exists for this fixture.",
                "does_not_claim": "run_is_blocked_or_unsafe",
            }
        ]

        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "blocked_by_required_context")
        self.assertEqual(
            summary["manual_review_findings"][0]["code"],
            "required_context_unavailable",
        )

    def test_workspace_or_environment_findings_keep_manual_review_needed(self) -> None:
        source = _load_input()
        source["review_area_inputs"]["workspace_findings"] = [
            {
                "prepared_run_context_id": "prepared-run-context-chevron-qA-0001",
                "code": "workspace_observation_has_review_findings",
                "severity": "review",
                "basis": {"changed_observed": 1},
                "does_not_claim": "run_is_blocked_or_workspace_is_unusable",
            }
        ]

        summary = build_prepared_run_acknowledgement_aware_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_workspace_review",
            {item["state"] for item in summary["review_items"]},
        )


if __name__ == "__main__":
    unittest.main()
