from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_approval_view_state import (
    build_prepared_run_approval_view_state_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_approval_view_state" / "basic_view"


def _load_input() -> dict:
    return json.loads((FIXTURE / "view-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-view-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunApprovalViewStateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_approval_view_state_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_approval_view_state_summary(source)

        source["operator_approval_summary"]["prepared_run_context"]["logical_targets"].append(
            "mutated"
        )
        source["operator_approval_summary"]["selected_parameter_state"]["state_id"] = "mutated"

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(summary["selected_parameter_state"]["state_id"], "param-state-0008")

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["view_state_policy"]["gui_workflow"] = "defined"

        with self.assertRaisesRegex(ValueError, "gui_workflow"):
            build_prepared_run_approval_view_state_summary(source)

    def test_approval_summary_must_not_claim_execution_effects(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["decision_effects"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_approval_view_state_summary(source)

    def test_view_request_must_match_approval_identity(self) -> None:
        source = _load_input()
        source["view_request"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter_state_id"):
            build_prepared_run_approval_view_state_summary(source)

    def test_rejected_approval_projects_rejected_view(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["classification"] = "operator_pre_run_review_rejected"
        source["operator_approval_summary"]["operator_decision"]["decision"] = (
            "reject_pre_run_review"
        )
        source["operator_approval_summary"]["operator_decision"]["approval_state"] = (
            "operator_rejected_review_recorded"
        )
        source["operator_approval_summary"]["operator_decision"]["rationale"] = (
            "Rejected until setup review is repeated."
        )

        summary = build_prepared_run_approval_view_state_summary(source)

        self.assertEqual(summary["classification"], "prepared_run_approval_view_rejected")
        self.assertIn("review_rejection_rationale", summary["available_review_actions"])
        self.assertEqual(summary["review_cards"][2]["decision_label"], "rejected")

    def test_deferred_approval_projects_deferred_view(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["classification"] = "operator_pre_run_review_deferred"
        source["operator_approval_summary"]["operator_decision"]["decision"] = (
            "defer_pre_run_review"
        )
        source["operator_approval_summary"]["operator_decision"]["approval_state"] = (
            "operator_deferred_review_recorded"
        )

        summary = build_prepared_run_approval_view_state_summary(source)

        self.assertEqual(summary["classification"], "prepared_run_approval_view_deferred")
        self.assertIn("review_deferral_rationale", summary["available_review_actions"])
        self.assertEqual(summary["review_cards"][2]["decision_label"], "deferred")

    def test_remaining_findings_keep_view_in_needs_review(self) -> None:
        source = _load_input()
        source["operator_approval_summary"]["carried_review_facts"]["manual_review_findings"] = [
            {
                "source_area": "workspace",
                "code": "workspace_observation_has_review_findings",
                "severity": "review",
                "basis": {"changed_observed": 1},
                "does_not_claim": "run_is_blocked_or_workspace_is_unusable",
            }
        ]

        summary = build_prepared_run_approval_view_state_summary(source)

        self.assertEqual(summary["classification"], "prepared_run_approval_view_needs_review")
        self.assertEqual(summary["review_cards"][1]["manual_review_finding_count"], 1)

    def test_debug_attachments_are_optional_derivative_evidence(self) -> None:
        source = _load_input()
        source["debug_attachments"] = [
            {
                "attachment_id": "debug-compatibility-json-0001",
                "artifact_posture": "debug_attachment_reference",
                "source_authority": "user_supplied",
                "payload_import": "not_performed",
                "relation_to_parameter_context": "derivative_debug_evidence",
            }
        ]

        summary = build_prepared_run_approval_view_state_summary(source)

        self.assertEqual(summary["debug_attachments"]["state"], "debug_attachments_present")
        self.assertEqual(summary["debug_attachments"]["count"], 1)
        self.assertEqual(
            summary["debug_attachments"]["attachment_refs"][0]["payload_import"],
            "not_performed",
        )

    def test_compatibility_artifacts_must_not_be_direct_context_input(self) -> None:
        source = _load_input()
        source["compatibility_artifacts"] = [
            {"artifact_id": "compatibility-output-0001"},
        ]

        with self.assertRaisesRegex(ValueError, "debug_attachments"):
            build_prepared_run_approval_view_state_summary(source)


if __name__ == "__main__":
    unittest.main()
