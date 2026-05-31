from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_operator_pre_run_approval import (
    build_prepared_run_operator_pre_run_approval_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_operator_pre_run_approval" / "basic_approval"


def _load_input() -> dict:
    return json.loads((FIXTURE / "approval-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-approval-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunOperatorPreRunApprovalSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_operator_pre_run_approval_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_operator_pre_run_approval_summary(source)

        source["acknowledgement_aware_review_summary"]["prepared_run_context"][
            "logical_targets"
        ].append("mutated")
        source["acknowledgement_aware_review_summary"]["acknowledged_review_findings"][0]["basis"][
            "missing_targets"
        ].append("mutated")

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(
            summary["carried_review_facts"]["acknowledged_review_findings"][0]["basis"],
            {"covered_targets": ["qA"], "missing_targets": ["cAB"]},
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["operator_approval_policy"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_review_summary_must_not_claim_execution(self) -> None:
        source = _load_input()
        source["acknowledgement_aware_review_summary"]["gate_decision"]["run_start_claim"] = (
            "claimed"
        )

        with self.assertRaisesRegex(ValueError, "run_start_claim"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_operator_decision_must_match_review_gate(self) -> None:
        source = _load_input()
        source["operator_decision"]["review_gate_id"] = "other-review-gate"

        with self.assertRaisesRegex(ValueError, "review_gate_id"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_operator_decision_must_match_parameter_state(self) -> None:
        source = _load_input()
        source["operator_decision"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter_state_id"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_unsupported_decision_is_rejected(self) -> None:
        source = _load_input()
        source["operator_decision"]["decision"] = "start_run_now"

        with self.assertRaisesRegex(ValueError, "unsupported"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_approval_requires_ready_review_state(self) -> None:
        source = _load_input()
        source["acknowledgement_aware_review_summary"]["gate_decision"]["overall_state"] = (
            "manual_pre_run_review_needed"
        )

        with self.assertRaisesRegex(ValueError, "ready_for_operator_pre_run_decision"):
            build_prepared_run_operator_pre_run_approval_summary(source)

    def test_rejection_records_rationale_without_ready_review_requirement(self) -> None:
        source = _load_input()
        source["acknowledgement_aware_review_summary"]["gate_decision"]["overall_state"] = (
            "manual_pre_run_review_needed"
        )
        source["operator_decision"]["decision"] = "reject_pre_run_review"
        source["operator_decision"]["rationale"] = "Reject until workspace finding is resolved."

        summary = build_prepared_run_operator_pre_run_approval_summary(source)

        self.assertEqual(summary["classification"], "operator_pre_run_review_rejected")
        self.assertEqual(
            summary["operator_decision"]["approval_state"],
            "operator_rejected_review_recorded",
        )
        self.assertEqual(summary["decision_effects"]["automatic_run_start"], "not_performed")

    def test_deferral_records_rationale_without_context_mutation(self) -> None:
        source = _load_input()
        source["operator_decision"]["decision"] = "defer_pre_run_review"
        source["operator_decision"]["rationale"] = "Defer until the operator confirms timing."

        summary = build_prepared_run_operator_pre_run_approval_summary(source)

        self.assertEqual(summary["classification"], "operator_pre_run_review_deferred")
        self.assertEqual(
            summary["operator_decision"]["approval_state"],
            "operator_deferred_review_recorded",
        )
        self.assertEqual(summary["decision_effects"]["durable_storage"], "not_performed")


if __name__ == "__main__":
    unittest.main()
