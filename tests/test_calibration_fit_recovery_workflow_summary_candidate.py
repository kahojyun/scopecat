from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_recovery_workflow import (
    build_fit_recovery_workflow_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_recovery_workflow"
    / "no_signal_and_visible_refit"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "recovery-workflow-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads(
        (FIXTURE / "expected-recovery-workflow-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationFitRecoveryWorkflowSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_recovery_workflow_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)
        self.assertNotIn("replay_harness", summary)

    def test_summary_separates_remeasurement_from_visible_signal_refit(self) -> None:
        summary = build_fit_recovery_workflow_summary(_load_input())
        recovery = {item["incident_id"]: item for item in summary["immediate_recovery"]}
        continuation = {item["incident_id"]: item for item in summary["continuation_readiness"]}
        offers = {item["incident_id"]: item for item in summary["dataset_selection_offers"]}

        self.assertEqual(recovery["incident-no-signal-readout-06001"]["action_family"], "remeasure")
        self.assertFalse(continuation["incident-no-signal-readout-06001"]["can_continue"])
        self.assertEqual(
            offers["incident-no-signal-readout-06001"]["state"],
            "withheld_for_remeasurement",
        )
        self.assertEqual(recovery["incident-rabi-visible-refit-06002"]["action_family"], "accept")
        self.assertTrue(continuation["incident-rabi-visible-refit-06002"]["can_continue"])
        self.assertEqual(
            offers["incident-rabi-visible-refit-06002"]["selected_fit_attempt_refs"],
            [
                "fit-attempt:rabi-06002-default-failed",
                "fit-attempt:rabi-06002-roi-guess-refit-accepted",
            ],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_fit_recovery_workflow_summary(source)

        source["workflow_context"]["target_group"] = "mutated"
        source["fit_recovery_incidents"][0]["measurement_ref"]["label"] = "mutated"

        self.assertEqual(summary["workflow_context"]["target_group"], "qA")
        self.assertEqual(
            summary["immediate_recovery"][0]["measurement_ref"]["label"],
            "Readout scan without visible response",
        )

    def test_duplicate_incident_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["fit_recovery_incidents"][0])
        source["fit_recovery_incidents"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate incident_id"):
            build_fit_recovery_workflow_summary(source)

    def test_chosen_recovery_action_must_be_available(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][0]["recovery"]["chosen_action"] = "missing"

        with self.assertRaisesRegex(ValueError, "chosen action is not available"):
            build_fit_recovery_workflow_summary(source)

    def test_no_signal_recovery_must_choose_remeasurement(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][0]["recovery"]["available_actions"].append(
            "accept_after_refit"
        )
        source["fit_recovery_incidents"][0]["recovery"]["chosen_action"] = "accept_after_refit"

        with self.assertRaisesRegex(ValueError, "no-signal recovery must choose remeasurement"):
            build_fit_recovery_workflow_summary(source)

    def test_accept_after_refit_requires_visible_signal(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["signal_assessment"]["classification"] = (
            "ambiguous_signal"
        )

        with self.assertRaisesRegex(ValueError, "accepted refit recovery requires visible signal"):
            build_fit_recovery_workflow_summary(source)

    def test_accept_after_refit_requires_accepted_current_attempt(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["fit_attempt"]["status"] = "fit_failed_exception"

        with self.assertRaisesRegex(
            ValueError, "accepted refit recovery requires accepted current attempt"
        ):
            build_fit_recovery_workflow_summary(source)

    def test_selected_attempts_must_exist_in_history(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["dataset_selection"]["selected_attempt_ids"].append(
            "fit-attempt:missing"
        )

        with self.assertRaisesRegex(ValueError, "selected fit attempt is not in history"):
            build_fit_recovery_workflow_summary(source)

    def test_selected_attempts_cannot_be_empty_for_history_case(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["dataset_selection"]["selected_attempt_ids"] = []

        with self.assertRaisesRegex(ValueError, "selected fit attempts cannot be empty"):
            build_fit_recovery_workflow_summary(source)

    def test_selected_case_must_declare_attempt_history(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["fit_attempt_history"] = []

        with self.assertRaisesRegex(
            ValueError, "selected validation case must declare fit attempt history"
        ):
            build_fit_recovery_workflow_summary(source)

    def test_selected_attempts_must_include_current_accepted_attempt(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["dataset_selection"]["selected_attempt_ids"] = [
            "fit-attempt:rabi-06002-default-failed"
        ]

        with self.assertRaisesRegex(
            ValueError, "selected attempts omit current accepted fit attempt"
        ):
            build_fit_recovery_workflow_summary(source)

    def test_selected_attempts_must_include_failed_prior_attempt(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["dataset_selection"]["selected_attempt_ids"] = [
            "fit-attempt:rabi-06002-roi-guess-refit-accepted"
        ]

        with self.assertRaisesRegex(ValueError, "selected attempts omit failed prior fit attempt"):
            build_fit_recovery_workflow_summary(source)

    def test_current_attempt_must_be_in_history(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["fit_attempt"]["attempt_id"] = "fit-attempt:missing"

        with self.assertRaisesRegex(ValueError, "current fit attempt is not in history"):
            build_fit_recovery_workflow_summary(source)

    def test_unselected_case_cannot_declare_selected_attempts(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][0]["dataset_selection"]["selected_attempt_ids"] = [
            "fit-attempt:readout-06001-no-signal"
        ]

        with self.assertRaisesRegex(
            ValueError, "unselected incident cannot declare selected fit attempts"
        ):
            build_fit_recovery_workflow_summary(source)

    def test_selected_case_missing_replay_context_gets_attention(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][1]["review_note_ref"] = None

        summary = build_fit_recovery_workflow_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-visible-refit-06002",
                    "missing": ["review_note_ref"],
                    "message": "Selected validation case is missing user-owned replay context.",
                }
            ],
        )

    def test_non_lab_internal_dataset_posture_gets_attention(self) -> None:
        source = _load_input()
        source["dataset_draft"]["posture"] = "portable_export_dataset"

        summary = build_fit_recovery_workflow_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"][0],
            {
                "code": "dataset_posture_not_lab_internal",
                "subject": "fit-validation-dataset-qA-0004",
                "posture": "portable_export_dataset",
                "message": (
                    "Dataset draft posture is outside the validated lab-internal boundary."
                ),
            },
        )

    def test_no_signal_case_selected_for_validation_gets_attention(self) -> None:
        source = _load_input()
        source["fit_recovery_incidents"][0]["dataset_selection"]["selected"] = True
        source["fit_recovery_incidents"][0]["dataset_selection"]["selected_attempt_ids"] = [
            "fit-attempt:readout-06001-no-signal"
        ]
        source["fit_recovery_incidents"][0]["fit_attempt_history"] = [
            {
                "attempt_id": "fit-attempt:readout-06001-no-signal",
                "order": 1,
                "status": "not_fit_no_clear_signal",
                "status_reason": "User review found no clear signal to fit.",
                "user_code_ref": "code:readout-fit-helper-v1",
                "fit_config_ref": "fit-config:readout-default-window",
                "config_labels": ["default_window"],
                "input_adjustments": [],
                "output_ref": "artifact:readout-no-signal-preview-06001",
                "declared_diagnostics": {
                    "fit_quality_facts": ["no_clear_signal"],
                    "score_policy": "user_declared_no_threshold",
                },
            }
        ]

        summary = build_fit_recovery_workflow_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"][0],
            {
                "code": "no_signal_case_selected_for_validation",
                "subject": "incident-no-signal-readout-06001",
                "message": (
                    "No-signal recovery case should be withheld until remeasurement is reviewed."
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
