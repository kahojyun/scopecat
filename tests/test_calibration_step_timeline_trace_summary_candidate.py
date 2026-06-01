from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_step_timeline_trace import (
    build_calibration_step_timeline_trace_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_step_timeline_trace" / "basic_trace"


def _load_input() -> dict:
    return json.loads((FIXTURE / "timeline-trace-input.json").read_text(encoding="utf-8"))


class CalibrationStepTimelineTraceSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_step_timeline_trace_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-timeline-trace-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_complete_trace_is_review_ready(self) -> None:
        summary = build_calibration_step_timeline_trace_summary(_load_input())
        traces = {item["step_record_id"]: item for item in summary["step_traces"]}

        trace = traces["step-record-rabi-qA-complete"]
        self.assertEqual(trace["timeline_status"], "timeline_order_review_ready")
        self.assertEqual(trace["events"][0]["reference_semantics"], "moving_selectors_allowed")
        self.assertEqual(trace["events"][1]["reference_semantics"], "resolved_snapshot")

    def test_out_of_order_missing_timestamp_and_missing_event_are_findings(self) -> None:
        summary = build_calibration_step_timeline_trace_summary(_load_input())
        findings = {
            (item["step_record_id"], item["finding"]) for item in summary["timeline_findings"]
        }

        self.assertIn(
            ("step-record-rabi-qB-out-of-order", "timeline_event_out_of_order"),
            findings,
        )
        self.assertIn(
            ("step-record-rabi-qC-missing-timestamp", "timeline_event_timestamp_missing"),
            findings,
        )
        self.assertIn(
            ("step-record-rabi-qD-missing-event", "timeline_expected_event_missing"),
            findings,
        )

    def test_timeline_findings_do_not_decide_workflow_actions(self) -> None:
        summary = build_calibration_step_timeline_trace_summary(_load_input())
        out_of_order = [
            item
            for item in summary["timeline_findings"]
            if item["finding"] == "timeline_event_out_of_order"
        ][0]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(out_of_order["does_not_claim"], "scheduler_or_executor_correction")
        self.assertEqual(
            attention["continuation_decision_not_performed"]["does_not_claim"],
            "calibration_workflow_decision",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["timeline_policy"]["scheduler"] = "defined"

        with self.assertRaisesRegex(ValueError, "scheduler"):
            build_calibration_step_timeline_trace_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["timeline_policy"]["event_repair"] = "performed"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_calibration_step_timeline_trace_summary(source)

    def test_event_must_reference_known_step(self) -> None:
        source = _load_input()
        source["timeline_events"][0]["step_record_id"] = "missing"

        with self.assertRaisesRegex(ValueError, "missing step record"):
            build_calibration_step_timeline_trace_summary(source)

    def test_intent_event_must_reference_step_intent(self) -> None:
        source = _load_input()
        source["timeline_events"][0]["refs"]["step_intent_id"] = "wrong"

        with self.assertRaisesRegex(ValueError, "step intent"):
            build_calibration_step_timeline_trace_summary(source)

    def test_intent_event_preserves_moving_selector_semantics(self) -> None:
        source = _load_input()
        source["timeline_events"][0]["refs"]["reference_semantics"] = "resolved_snapshot"

        with self.assertRaisesRegex(ValueError, "moving selector"):
            build_calibration_step_timeline_trace_summary(source)

    def test_context_event_must_record_resolved_snapshot(self) -> None:
        source = _load_input()
        source["timeline_events"][1]["refs"]["context_resolution_state"] = "moving_reference"

        with self.assertRaisesRegex(ValueError, "resolved snapshot"):
            build_calibration_step_timeline_trace_summary(source)

    def test_observation_event_must_remain_reference_only(self) -> None:
        source = _load_input()
        source["timeline_events"][2]["refs"]["payload_handling"] = "payload_read"

        with self.assertRaisesRegex(ValueError, "reference-only"):
            build_calibration_step_timeline_trace_summary(source)

    def test_fit_event_must_reference_fit_result_for_same_step(self) -> None:
        source = _load_input()
        source["timeline_events"][3]["refs"]["fit_result_id"] = "fit-result-rabi-qB-0001"

        with self.assertRaisesRegex(ValueError, "another step"):
            build_calibration_step_timeline_trace_summary(source)

    def test_write_review_event_state_must_match_write(self) -> None:
        source = _load_input()
        source["timeline_events"][5]["refs"]["review_state"] = "proposed_pending_review"

        with self.assertRaisesRegex(ValueError, "state must match"):
            build_calibration_step_timeline_trace_summary(source)

    def test_handoff_event_must_not_start_parameter_state_intake(self) -> None:
        source = _load_input()
        source["accepted_handoff_refs"][0]["parameter_state_intake_state"] = "started"

        with self.assertRaisesRegex(ValueError, "intake must not start"):
            build_calibration_step_timeline_trace_summary(source)

    def test_malformed_timestamp_is_rejected(self) -> None:
        source = _load_input()
        source["timeline_events"][0]["occurred_at"] = "2026-05-22 09:55:00"

        with self.assertRaisesRegex(ValueError, "UTC Z"):
            build_calibration_step_timeline_trace_summary(source)

    def test_duplicate_event_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["timeline_events"][0])
        source["timeline_events"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            build_calibration_step_timeline_trace_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_step_timeline_trace_summary(source)

        source["calibration_steps"][0]["target"] = "mutated"
        source["timeline_events"][0]["refs"]["step_intent_id"] = "mutated"
        source["accepted_handoff_refs"][0]["handoff_id"] = "mutated"

        self.assertEqual(summary["calibration_steps"][0]["target"], "qA")
        self.assertEqual(
            summary["step_traces"][0]["events"][0]["refs"]["step_intent_id"],
            "step-intent-rabi-qA-complete",
        )
        self.assertEqual(
            summary["accepted_handoff_refs"][0]["handoff_id"],
            "handoff-rabi-qA-0001",
        )


if __name__ == "__main__":
    unittest.main()
