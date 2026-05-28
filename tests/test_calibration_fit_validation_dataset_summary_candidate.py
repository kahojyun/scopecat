from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_validation_dataset import (
    build_fit_validation_dataset_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "calibration_fit_validation_dataset" / "basic_candidate_queue"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "fit-validation-input.json").read_text(encoding="utf-8"))


class CalibrationFitValidationDatasetSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-fit-validation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)

    def test_selected_dataset_cases_exclude_no_signal_remeasurement_case(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input())

        case_ids = [candidate["validation_case_id"] for candidate in summary["dataset_candidates"]]
        self.assertEqual(
            case_ids,
            [
                "validation-case-rabi-roi-failed",
                "validation-case-readout-score-reviewed",
            ],
        )
        self.assertEqual(
            summary["dataset_draft"]["withheld_incident_ids"],
            ["incident-no-signal-resonator"],
        )

    def test_recovery_actions_are_user_choices_not_scopecat_decisions(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input())
        actions = {action["action_id"]: action for action in summary["recovery_actions"]}

        self.assertTrue(
            actions["incident-no-signal-resonator:adjust_parameters_remeasure"]["chosen"]
        )
        self.assertTrue(actions["incident-rabi-roi-failed:adjust_roi_refit"]["chosen"])
        self.assertTrue(actions["incident-readout-score-reviewed:accept_after_review"]["chosen"])
        self.assertFalse(actions["incident-rabi-roi-failed:add_to_validation_dataset"]["chosen"])

    def test_selected_case_missing_replay_context_gets_attention(self) -> None:
        source = _load_input()
        del source["fit_incidents"][1]["measurement_ref"]["record_id"]
        del source["fit_incidents"][1]["fit_attempt"]["attempt_id"]
        source["fit_incidents"][1]["fit_attempt"]["user_code_ref"] = None
        source["fit_incidents"][1]["expected_replay_behavior"] = None

        summary = build_fit_validation_dataset_summary(source)

        candidates = {
            candidate["validation_case_id"]: candidate
            for candidate in summary["dataset_candidates"]
        }
        self.assertIsNone(candidates["validation-case-rabi-roi-failed"]["source_measurement_ref"])
        self.assertIsNone(candidates["validation-case-rabi-roi-failed"]["user_fit_attempt_ref"])
        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-roi-failed",
                    "missing": [
                        "measurement_ref.record_id",
                        "fit_attempt.attempt_id",
                        "fit_attempt.user_code_ref",
                        "expected_replay_behavior",
                    ],
                    "message": ("Selected validation case is missing user-owned replay context."),
                }
            ],
        )

    def test_non_lab_internal_dataset_posture_gets_attention(self) -> None:
        source = _load_input()
        source["dataset_draft"]["posture"] = "portable_export_dataset"

        summary = build_fit_validation_dataset_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "dataset_posture_not_lab_internal",
                    "subject": "fit-validation-dataset-qA-0001",
                    "posture": "portable_export_dataset",
                    "message": (
                        "Dataset draft posture is outside the validated lab-internal boundary."
                    ),
                }
            ],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_fit_validation_dataset_summary(source)

        source["fit_incidents"][0]["measurement_ref"]["label"] = "mutated"

        self.assertEqual(
            summary["queue"][0]["measurement_ref"]["label"],
            "Resonator scan with no visible dip",
        )

    def test_duplicate_incident_ids_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["fit_incidents"][0])
        source["fit_incidents"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate incident_id"):
            build_fit_validation_dataset_summary(source)

    def test_derived_validation_case_ids_must_be_unique(self) -> None:
        source = _load_input()
        colliding = copy.deepcopy(source["fit_incidents"][1])
        colliding["incident_id"] = "rabi-roi-failed"
        source["fit_incidents"].append(colliding)

        with self.assertRaisesRegex(ValueError, "duplicate validation_case_id"):
            build_fit_validation_dataset_summary(source)

    def test_chosen_recovery_action_must_be_available(self) -> None:
        source = _load_input()
        source["fit_incidents"][0]["recovery"]["chosen_action"] = "missing_action"

        with self.assertRaisesRegex(ValueError, "chosen action is not available"):
            build_fit_validation_dataset_summary(source)


if __name__ == "__main__":
    unittest.main()
