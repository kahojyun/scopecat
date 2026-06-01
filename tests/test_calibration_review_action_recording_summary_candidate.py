from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_review_action_recording import (
    build_calibration_review_action_recording_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"


def _load_input() -> dict:
    return json.loads((FIXTURE / "action-recording-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads(
        (FIXTURE / "expected-action-recording-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationReviewActionRecordingSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_calibration_review_action_recording_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_records_events_without_execution(self) -> None:
        summary = build_calibration_review_action_recording_summary(_load_input())

        self.assertEqual(summary["recorded_event_count"], 2)
        self.assertEqual(
            {event["execution_state"] for event in summary["recorded_events"]},
            {"not_executed"},
        )
        self.assertEqual(
            summary["recording_classification"],
            "review_action_choices_recorded_without_execution",
        )

    def test_positive_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["action_recording_policy"]["action_execution"] = "performed"

        with self.assertRaisesRegex(ValueError, "action_execution"):
            build_calibration_review_action_recording_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["action_recording_policy"]["workflow_transition"] = "performed"

        with self.assertRaisesRegex(ValueError, "policy shape"):
            build_calibration_review_action_recording_summary(source)

    def test_forbidden_command_fields_are_rejected(self) -> None:
        source = _load_input()
        source["action_events"][0]["command"] = "run_fit"

        with self.assertRaisesRegex(ValueError, "command"):
            build_calibration_review_action_recording_summary(source)

    def test_event_must_reference_available_surface_label(self) -> None:
        source = _load_input()
        source["action_events"][0]["action_label"] = "run_fit"

        with self.assertRaisesRegex(ValueError, "available surface action label"):
            build_calibration_review_action_recording_summary(source)

    def test_event_must_remain_not_executed(self) -> None:
        source = _load_input()
        source["action_events"][0]["execution_state"] = "executed"

        with self.assertRaisesRegex(ValueError, "must not execute"):
            build_calibration_review_action_recording_summary(source)

    def test_event_posture_must_remain_audit_intent_only(self) -> None:
        source = _load_input()
        source["action_events"][0]["event_posture"] = "workflow_mutation"

        with self.assertRaisesRegex(ValueError, "audit intent"):
            build_calibration_review_action_recording_summary(source)

    def test_duplicate_event_order_is_rejected(self) -> None:
        source = _load_input()
        source["action_events"][1]["order"] = 1

        with self.assertRaisesRegex(ValueError, "duplicate event order"):
            build_calibration_review_action_recording_summary(source)

    def test_timestamp_must_be_utc_seconds(self) -> None:
        source = _load_input()
        source["action_events"][0]["recorded_at"] = "2026-05-23 11:00"

        with self.assertRaisesRegex(ValueError, "UTC second timestamp"):
            build_calibration_review_action_recording_summary(source)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_review_action_recording_summary(source)

        source["action_events"][0]["reason"] = "mutated"
        source["review_surface_summary"]["surface_request"]["surface_id"] = "mutated"

        self.assertEqual(
            summary["recorded_events"][0]["reason"],
            "Reviewer chose to record the fit review outcome after inspecting the card.",
        )
        self.assertEqual(
            summary["surface_ref"]["surface_id"], "calibration-continuation-surface-0001"
        )

    def test_duplicate_surface_palette_labels_are_rejected(self) -> None:
        source = _load_input()
        source["review_surface_summary"]["action_palette"].append(
            copy.deepcopy(source["review_surface_summary"]["action_palette"][0])
        )

        with self.assertRaisesRegex(ValueError, "duplicate action palette"):
            build_calibration_review_action_recording_summary(source)


if __name__ == "__main__":
    unittest.main()
