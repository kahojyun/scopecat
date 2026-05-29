from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_recovery_review_state import (
    build_fit_recovery_review_state_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_recovery_review_state"
    / "no_signal_and_visible_refit_review"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-state-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads((FIXTURE / "expected-review-state-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class CalibrationFitRecoveryReviewStateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_recovery_review_state_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("gui_component", summary)
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)
        self.assertNotIn("replay_harness", summary)

    def test_review_state_exposes_cards_actions_controls_and_banner(self) -> None:
        summary = build_fit_recovery_review_state_summary(_load_input())

        cards = {card["incident_id"]: card for card in summary["incident_cards"]}
        controls = {
            control["incident_id"]: control for control in summary["dataset_selection_controls"]
        }
        actions = {action["incident_id"]: action for action in summary["primary_actions"]}

        self.assertEqual(cards["incident-no-signal-readout-06001"]["severity"], "blocking")
        self.assertEqual(
            cards["incident-rabi-visible-refit-06002"]["severity"],
            "ready_with_dataset_case",
        )
        self.assertEqual(
            actions["incident-no-signal-readout-06001"]["label"],
            "Adjust parameters and remeasure",
        )
        self.assertFalse(controls["incident-no-signal-readout-06001"]["enabled"])
        self.assertTrue(controls["incident-rabi-visible-refit-06002"]["enabled"])
        self.assertEqual(summary["continuation_banner"]["state"], "blocked")

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_fit_recovery_review_state_summary(source)

        source["review_surface"]["selected_incident_id"] = "mutated"
        source["recovery_workflow_input"]["fit_recovery_incidents"][0]["labels"].append("mutated")

        self.assertEqual(
            summary["surface_context"]["selected_incident_id"],
            "incident-no-signal-readout-06001",
        )
        self.assertNotIn("mutated", summary["incident_cards"][0]["badges"])

    def test_selected_surface_incident_must_exist(self) -> None:
        source = _load_input()
        source["review_surface"]["selected_incident_id"] = "incident-missing"

        with self.assertRaisesRegex(ValueError, "review surface selects missing incident"):
            build_fit_recovery_review_state_summary(source)

    def test_review_surface_must_stay_local_review_state(self) -> None:
        source = _load_input()
        source["review_surface"]["surface_kind"] = "gui_component"

        with self.assertRaisesRegex(ValueError, "unsupported review surface kind"):
            build_fit_recovery_review_state_summary(source)

    def test_child_workflow_validation_errors_are_preserved(self) -> None:
        source = _load_input()
        source["recovery_workflow_input"]["fit_recovery_incidents"][0]["recovery"][
            "chosen_action"
        ] = "missing"

        with self.assertRaisesRegex(ValueError, "chosen action is not available"):
            build_fit_recovery_review_state_summary(source)

    def test_child_workflow_action_compatibility_errors_are_preserved(self) -> None:
        source = _load_input()
        recovery = source["recovery_workflow_input"]["fit_recovery_incidents"][0]["recovery"]
        recovery["available_actions"].append("accept_after_refit")
        recovery["chosen_action"] = "accept_after_refit"

        with self.assertRaisesRegex(ValueError, "no-signal recovery must choose remeasurement"):
            build_fit_recovery_review_state_summary(source)

    def test_no_signal_selected_dataset_offer_is_projected_as_disabled_control(self) -> None:
        source = _load_input()
        incident = source["recovery_workflow_input"]["fit_recovery_incidents"][0]
        current_attempt = copy.deepcopy(incident["fit_attempt"])
        current_attempt["order"] = 1
        incident["fit_attempt_history"] = [current_attempt]
        incident["dataset_selection"] = {
            "selected": True,
            "selected_attempt_ids": [current_attempt["attempt_id"]],
            "reason": "Operator marked this no-signal case for later review.",
        }

        summary = build_fit_recovery_review_state_summary(source)
        cards = {card["incident_id"]: card for card in summary["incident_cards"]}
        controls = {
            control["incident_id"]: control for control in summary["dataset_selection_controls"]
        }
        actions = {action["incident_id"]: action for action in summary["primary_actions"]}

        self.assertFalse(controls["incident-no-signal-readout-06001"]["selected"])
        self.assertFalse(controls["incident-no-signal-readout-06001"]["enabled"])
        self.assertEqual(
            controls["incident-no-signal-readout-06001"]["selected_fit_attempt_refs"],
            [],
        )
        self.assertIsNone(controls["incident-no-signal-readout-06001"]["validation_case_id"])
        self.assertEqual(
            cards["incident-no-signal-readout-06001"]["dataset_selection_state"],
            "withheld_for_remeasurement",
        )
        self.assertEqual(
            actions["incident-no-signal-readout-06001"]["dataset_effect"],
            "withheld_for_remeasurement",
        )

    def test_missing_replay_context_is_projected(self) -> None:
        source = _load_input()
        source["recovery_workflow_input"]["fit_recovery_incidents"][1]["review_note_ref"] = None

        summary = build_fit_recovery_review_state_summary(source)

        self.assertEqual(
            summary["missing_context"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-visible-refit-06002",
                    "missing": ["review_note_ref"],
                    "message": "Selected validation case is missing user-owned replay context.",
                }
            ],
        )
        self.assertEqual(summary["attention"], summary["missing_context"])

    def test_continuation_banner_can_be_ready_when_all_incidents_can_continue(self) -> None:
        source = _load_input()
        incidents = source["recovery_workflow_input"]["fit_recovery_incidents"]
        incidents[:] = [incidents[1]]
        source["review_surface"]["selected_incident_id"] = "incident-rabi-visible-refit-06002"

        summary = build_fit_recovery_review_state_summary(source)

        self.assertEqual(summary["continuation_banner"]["state"], "can_continue")
        self.assertEqual(
            summary["continuation_banner"]["ready_incident_ids"],
            ["incident-rabi-visible-refit-06002"],
        )
        self.assertEqual(summary["continuation_banner"]["blocked_incident_ids"], [])

    def test_continuation_banner_does_not_block_skipped_incidents(self) -> None:
        source = _load_input()
        incidents = source["recovery_workflow_input"]["fit_recovery_incidents"]
        incidents[:] = [incidents[1]]
        source["review_surface"]["selected_incident_id"] = "incident-rabi-visible-refit-06002"
        incident = incidents[0]
        incident["recovery"]["available_actions"].append("skip_target")
        incident["recovery"]["chosen_action"] = "skip_target"
        incident["dataset_selection"] = {
            "selected": False,
            "reason": "Skipped target is not selected for validation.",
        }

        summary = build_fit_recovery_review_state_summary(source)

        self.assertEqual(
            summary["continuation_banner"]["state"],
            "no_continuation_target",
        )
        self.assertEqual(summary["continuation_banner"]["blocked_incident_ids"], [])
        self.assertEqual(summary["continuation_banner"]["ready_incident_ids"], [])

    def test_no_signal_dataset_control_stays_disabled_even_if_attention_exists(self) -> None:
        source = _load_input()
        source["recovery_workflow_input"]["dataset_draft"]["posture"] = "portable_export_dataset"

        summary = build_fit_recovery_review_state_summary(source)
        control = summary["dataset_selection_controls"][0]

        self.assertFalse(control["enabled"])
        self.assertEqual(
            control["disabled_reason"],
            "No clear signal should be remeasured before dataset selection.",
        )
        self.assertEqual(summary["attention"][0]["code"], "dataset_posture_not_lab_internal")


if __name__ == "__main__":
    unittest.main()
