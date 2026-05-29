from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_recovery_interaction_recording import (
    build_fit_recovery_interaction_recording_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_recovery_interaction_recording"
    / "no_signal_and_visible_refit_events"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "interaction-recording-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads(
        (FIXTURE / "expected-interaction-recording-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationFitRecoveryInteractionRecordingSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_recovery_interaction_recording_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("gui_event_log", summary)
        self.assertNotIn("notebook_execution", summary)
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)
        self.assertNotIn("replay_harness", summary)

    def test_events_project_no_signal_remeasurement_and_visible_refit_selection(self) -> None:
        summary = build_fit_recovery_interaction_recording_summary(_load_input())
        outcomes = {outcome["incident_id"]: outcome for outcome in summary["interaction_outcomes"]}

        no_signal = outcomes["incident-no-signal-readout-07001"]
        self.assertEqual(no_signal["signal_classification"], "no_clear_signal")
        self.assertEqual(no_signal["chosen_action"], "adjust_parameters_remeasure")
        self.assertEqual(no_signal["continuation_status"], "requires_remeasurement")
        self.assertFalse(no_signal["dataset_control_enabled"])

        visible = outcomes["incident-rabi-visible-refit-07002"]
        self.assertEqual(visible["chosen_action"], "accept_after_refit")
        self.assertTrue(visible["can_continue"])
        self.assertTrue(visible["dataset_control_selected"])
        self.assertEqual(visible["review_card_severity"], "ready_with_dataset_case")

    def test_recorded_review_context_projects_note_and_replay_events(self) -> None:
        summary = build_fit_recovery_interaction_recording_summary(_load_input())

        self.assertEqual(
            summary["recorded_review_context"],
            [
                {
                    "incident_id": "incident-no-signal-readout-07001",
                    "review_note_ref": "note:readout-no-signal-remeasure",
                    "expected_replay_behavior_recorded": False,
                },
                {
                    "incident_id": "incident-rabi-visible-refit-07002",
                    "review_note_ref": "note:rabi-visible-refit-accepted",
                    "expected_replay_behavior_recorded": True,
                },
            ],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_fit_recovery_interaction_recording_summary(source)

        source["recording_context"]["target_group"] = "mutated"
        source["interaction_events"][0]["event_id"] = "mutated"

        self.assertEqual(summary["recording_context"]["target_group"], "qA")
        self.assertEqual(
            summary["applied_events"][0]["event_id"],
            "interaction-event-classify-no-signal-07001",
        )

    def test_unknown_event_type_is_rejected(self) -> None:
        source = _load_input()
        source["interaction_events"][0]["event_type"] = "run_fit"

        with self.assertRaisesRegex(ValueError, "unsupported interaction event type"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_duplicate_event_order_is_rejected(self) -> None:
        source = _load_input()
        source["interaction_events"][1]["order"] = source["interaction_events"][0]["order"]

        with self.assertRaisesRegex(ValueError, "duplicate event order"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_missing_incident_reference_is_rejected(self) -> None:
        source = _load_input()
        source["interaction_events"][0]["incident_id"] = "incident-missing"

        with self.assertRaisesRegex(ValueError, "references missing incident"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_unsupported_signal_classification_is_rejected(self) -> None:
        source = _load_input()
        source["interaction_events"][0]["classification"] = "definitely_good_signal"

        with self.assertRaisesRegex(ValueError, "unsupported signal classification"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_no_signal_interaction_cannot_select_validation_case(self) -> None:
        source = _load_input()
        source["interaction_events"].insert(
            3,
            {
                "event_id": "interaction-event-invalid-no-signal-selection",
                "order": 3.5,
                "event_type": "select_validation_case",
                "incident_id": "incident-no-signal-readout-07001",
                "selected": True,
                "selected_attempt_ids": ["fit-attempt:readout-07001-no-signal"],
                "reason": "Invalid no-signal validation selection.",
                "authority": "fixture_declared_user_choice",
            },
        )

        with self.assertRaisesRegex(ValueError, "no-signal interaction cannot select"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_selected_case_cannot_be_reclassified_to_final_no_signal(self) -> None:
        source = _load_input()
        readout = source["workflow_input_before"]["fit_recovery_incidents"][0]
        readout["fit_attempt_history"] = [
            {
                "attempt_id": "fit-attempt:readout-07001-no-signal",
                "order": 1,
                "status": "fit_failed_exception",
                "status_reason": "Initial default fit did not produce a usable result.",
                "user_code_ref": "code:readout-fit-helper-v1",
                "fit_config_ref": "fit-config:readout-default-window",
                "output_ref": "artifact:readout-no-signal-preview-07001",
            }
        ]
        source["interaction_events"].insert(
            0,
            {
                "event_id": "interaction-event-invalid-early-readout-selection",
                "order": 0,
                "event_type": "select_validation_case",
                "incident_id": "incident-no-signal-readout-07001",
                "selected": True,
                "selected_attempt_ids": ["fit-attempt:readout-07001-no-signal"],
                "reason": "Invalid early selection before no-signal classification.",
                "authority": "fixture_declared_user_choice",
            },
        )

        with self.assertRaisesRegex(ValueError, "no-signal final state cannot select"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_visible_selected_case_requires_failed_and_refit_context(self) -> None:
        source = _load_input()
        for event in source["interaction_events"]:
            if event["event_id"] == "interaction-event-select-visible-case-07006":
                event["selected_attempt_ids"] = ["fit-attempt:rabi-07002-roi-guess-refit-accepted"]

        with self.assertRaisesRegex(ValueError, "selected attempts omit failed prior"):
            build_fit_recovery_interaction_recording_summary(source)

    def test_accepted_refit_requires_accepted_current_attempt(self) -> None:
        source = _load_input()
        incident = source["workflow_input_before"]["fit_recovery_incidents"][1]
        incident["fit_attempt"]["status"] = "fit_failed_exception"
        for attempt in incident["fit_attempt_history"]:
            if attempt["attempt_id"] == incident["fit_attempt"]["attempt_id"]:
                attempt["status"] = "fit_failed_exception"

        with self.assertRaisesRegex(
            ValueError, "accepted refit recovery requires accepted current attempt"
        ):
            build_fit_recovery_interaction_recording_summary(source)

    def test_missing_replay_context_remains_attention_not_execution(self) -> None:
        source = _load_input()
        source["interaction_events"] = [
            event
            for event in source["interaction_events"]
            if event["event_id"] != "interaction-event-record-visible-replay-07005"
        ]

        summary = build_fit_recovery_interaction_recording_summary(source)

        self.assertEqual(
            summary["missing_context"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-visible-refit-07002",
                    "missing": ["review_note_ref", "expected_replay_behavior"],
                    "message": "Selected validation case is missing user-owned replay context.",
                }
            ],
        )
        self.assertEqual(summary["attention"], summary["missing_context"])

    def test_skipped_target_is_not_blocked_continuation(self) -> None:
        source = _load_input()
        source["interaction_events"] = [
            {
                "event_id": "interaction-event-skip-visible-target",
                "order": 1,
                "event_type": "choose_recovery_action",
                "incident_id": "incident-rabi-visible-refit-07002",
                "action": "skip_target",
                "authority": "fixture_declared_user_choice",
            },
            {
                "event_id": "interaction-event-select-skipped-review-card",
                "order": 2,
                "event_type": "select_review_incident",
                "incident_id": "incident-rabi-visible-refit-07002",
                "authority": "fixture_declared_user_navigation",
            },
        ]
        source["workflow_input_before"]["fit_recovery_incidents"] = [
            source["workflow_input_before"]["fit_recovery_incidents"][1]
        ]

        summary = build_fit_recovery_interaction_recording_summary(source)

        self.assertEqual(
            summary["interaction_outcomes"],
            [
                {
                    "incident_id": "incident-rabi-visible-refit-07002",
                    "signal_classification": "visible_signal",
                    "chosen_action": "skip_target",
                    "continuation_status": "skipped",
                    "can_continue": False,
                    "dataset_offer_state": "withheld",
                    "dataset_control_enabled": True,
                    "dataset_control_selected": False,
                    "review_card_severity": "informational",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
