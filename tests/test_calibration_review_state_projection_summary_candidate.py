from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_review_state_projection import (
    build_calibration_review_state_projection_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_review_state_projection" / "basic_projection"


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-state-projection-input.json").read_text(encoding="utf-8"))


class CalibrationReviewStateProjectionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_review_state_projection_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-review-state-projection-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_projects_core_review_states(self) -> None:
        summary = build_calibration_review_state_projection_summary(_load_input())
        cards = {item["step_record_id"]: item for item in summary["review_cards"]}

        self.assertEqual(
            cards["step-record-rabi-qA-ready"]["review_state"],
            "handoff_ready_for_parameter_state_thread",
        )
        self.assertEqual(
            cards["step-record-rabi-qB-missing-observation"]["review_state"],
            "needs_observation_evidence",
        )
        self.assertEqual(
            cards["step-record-rabi-qC-fit-review"]["review_state"],
            "needs_fit_review",
        )
        self.assertEqual(
            cards["step-record-rabi-qD-write-review"]["review_state"],
            "needs_write_review",
        )
        self.assertEqual(
            cards["step-record-rabi-qE-timeline"]["review_state"],
            "needs_timeline_order_review",
        )

    def test_available_actions_are_labels_only(self) -> None:
        summary = build_calibration_review_state_projection_summary(_load_input())
        ready = summary["review_cards"][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(ready["action_posture"], "labels_only_not_executed")
        self.assertEqual(
            ready["available_review_actions"],
            ["inspect_handoff", "wait_for_parameter_state_thread"],
        )
        self.assertEqual(
            attention["available_actions_are_labels_only"]["does_not_claim"],
            "action_execution",
        )

    def test_timeline_issue_takes_precedence_over_handoff_ready(self) -> None:
        summary = build_calibration_review_state_projection_summary(_load_input())
        card = {item["step_record_id"]: item for item in summary["review_cards"]}[
            "step-record-rabi-qE-timeline"
        ]

        self.assertEqual(card["state_source"], "timeline")
        self.assertEqual(card["evidence_review_state"], "complete_until_parameter_state_intake")
        self.assertEqual(card["review_state"], "needs_timeline_order_review")

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_state_policy"]["action_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "action_execution"):
            build_calibration_review_state_projection_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["review_state_policy"]["gui_component"] = "defined"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_review_state_projection_summary(source)

    def test_summary_inputs_must_cover_every_step(self) -> None:
        source = _load_input()
        source["timeline_traces"].pop()

        with self.assertRaisesRegex(ValueError, "cover every review step"):
            build_calibration_review_state_projection_summary(source)

    def test_bundle_chain_must_remain_read_only(self) -> None:
        source = _load_input()
        source["review_bundle_chains"][0]["bundle_posture"] = "state_mutation"

        with self.assertRaisesRegex(ValueError, "read-only"):
            build_calibration_review_state_projection_summary(source)

    def test_parameter_state_intake_must_not_start(self) -> None:
        source = _load_input()
        source["evidence_completeness"][0]["parameter_state_intake_state"] = "started"

        with self.assertRaisesRegex(ValueError, "intake must not start"):
            build_calibration_review_state_projection_summary(source)

    def test_timeline_trace_must_remain_read_only(self) -> None:
        source = _load_input()
        source["timeline_traces"][0]["trace_posture"] = "scheduler_input"

        with self.assertRaisesRegex(ValueError, "read-only"):
            build_calibration_review_state_projection_summary(source)

    def test_findings_must_reference_known_step(self) -> None:
        source = _load_input()
        source["review_findings"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_review_state_projection_summary(source)

    def test_findings_must_remain_review_only(self) -> None:
        source = _load_input()
        source["review_findings"][0]["finding_posture"] = "automatic_retry"

        with self.assertRaisesRegex(ValueError, "review-only"):
            build_calibration_review_state_projection_summary(source)

    def test_findings_must_not_claim_workflow_action(self) -> None:
        source = _load_input()
        source["review_findings"][0]["does_not_claim"] = "nothing"

        with self.assertRaisesRegex(ValueError, "workflow action"):
            build_calibration_review_state_projection_summary(source)

    def test_duplicate_finding_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["review_findings"][0])
        source["review_findings"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate finding_id"):
            build_calibration_review_state_projection_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_review_state_projection_summary(source)

        source["review_steps"][0]["target"] = "mutated"
        source["review_findings"][0]["finding"] = "mutated"
        source["timeline_traces"][0]["timeline_status"] = "timeline_order_needs_review"

        self.assertEqual(summary["review_steps"][0]["target"], "qA")
        self.assertEqual(summary["review_findings"][0]["finding"], "missing_observation_evidence")
        self.assertEqual(
            summary["review_cards"][0]["timeline_status"], "timeline_order_review_ready"
        )


if __name__ == "__main__":
    unittest.main()
