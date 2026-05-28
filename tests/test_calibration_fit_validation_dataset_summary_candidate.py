from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_validation_dataset import (
    build_fit_validation_dataset_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "calibration_fit_validation_dataset"
BASIC_FIXTURE = FIXTURE_ROOT / "basic_candidate_queue"
REPEATED_FIXTURE = FIXTURE_ROOT / "repeated_attempt_history"


def _load_input(fixture: Path = BASIC_FIXTURE) -> dict:
    return json.loads((fixture / "fit-validation-input.json").read_text(encoding="utf-8"))


def _load_expected(fixture: Path = BASIC_FIXTURE) -> dict:
    return json.loads(
        (fixture / "expected-fit-validation-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class CalibrationFitValidationDatasetSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input())
        expected = _load_expected()

        self.assertEqual(summary, expected)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)

    def test_builds_expected_repeated_attempt_history_summary(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input(REPEATED_FIXTURE))

        self.assertEqual(summary, _load_expected(REPEATED_FIXTURE))
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)
        self.assertNotIn("replay_harness", summary)

    def test_repeated_attempt_summary_preserves_user_selected_attempts(self) -> None:
        summary = build_fit_validation_dataset_summary(_load_input(REPEATED_FIXTURE))

        candidate = summary["dataset_candidates"][0]
        self.assertEqual(
            candidate["source_fit_attempt_refs"],
            [
                "fit-attempt:rabi-0101-default-failed",
                "fit-attempt:rabi-0101-roi-refit-accepted",
            ],
        )
        self.assertEqual(summary["queue"][0]["fit_attempt_history_count"], 2)
        self.assertEqual(
            summary["attempt_histories"][0]["attempts"][1]["input_adjustments"],
            [
                "roi_narrowed_to_visible_oscillation",
                "initial_guess_seeded_from_neighboring_period",
            ],
        )
        self.assertEqual(
            summary["attempt_histories"][0]["attempts"][0]["declared_diagnostics"]["score_policy"],
            "user_declared_no_threshold",
        )

    def test_single_selected_history_attempt_drives_candidate_primary_refs(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["dataset_selection"]["selected_attempt_ids"] = [
            "fit-attempt:rabi-0101-default-failed"
        ]

        summary = build_fit_validation_dataset_summary(source)

        candidate = summary["dataset_candidates"][0]
        self.assertEqual(
            candidate["user_fit_attempt_ref"],
            "fit-attempt:rabi-0101-default-failed",
        )
        self.assertEqual(candidate["fit_config_ref"], "fit-config:rabi-default-roi")
        self.assertEqual(
            candidate["selected_fit_attempts"],
            [
                {
                    "attempt_id": "fit-attempt:rabi-0101-default-failed",
                    "status": "fit_failed_exception",
                    "user_code_ref": "code:rabi-fit-helper-v2",
                    "fit_config_ref": "fit-config:rabi-default-roi",
                }
            ],
        )

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

    def test_duplicate_fit_attempt_history_ids_are_rejected(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        incident = source["fit_incidents"][0]
        duplicate = copy.deepcopy(incident["fit_attempt_history"][0])
        incident["fit_attempt_history"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate attempt_id"):
            build_fit_validation_dataset_summary(source)

    def test_current_fit_attempt_must_be_in_history(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["fit_attempt"]["attempt_id"] = "fit-attempt:missing"

        with self.assertRaisesRegex(ValueError, "current fit attempt is not in history"):
            build_fit_validation_dataset_summary(source)

    def test_selected_fit_attempts_must_be_in_history(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["dataset_selection"]["selected_attempt_ids"].append(
            "fit-attempt:missing"
        )

        with self.assertRaisesRegex(ValueError, "selected fit attempt is not in history"):
            build_fit_validation_dataset_summary(source)

    def test_selected_fit_attempts_cannot_be_empty(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["dataset_selection"]["selected_attempt_ids"] = []

        with self.assertRaisesRegex(ValueError, "selected fit attempts cannot be empty"):
            build_fit_validation_dataset_summary(source)

    def test_duplicate_selected_fit_attempts_are_rejected(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["dataset_selection"]["selected_attempt_ids"].append(
            "fit-attempt:rabi-0101-default-failed"
        )

        with self.assertRaisesRegex(ValueError, "duplicate selected_attempt_id"):
            build_fit_validation_dataset_summary(source)

    def test_unselected_history_case_has_no_selected_attempt_refs(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        incident = source["fit_incidents"][0]
        incident["dataset_selection"]["selected"] = False
        del incident["dataset_selection"]["selected_attempt_ids"]

        summary = build_fit_validation_dataset_summary(source)

        self.assertEqual(summary["dataset_candidates"], [])
        self.assertEqual(summary["queue"][0]["selected_fit_attempt_refs"], [])
        self.assertEqual(summary["attempt_histories"][0]["selected_fit_attempt_refs"], [])
        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])

    def test_unselected_history_case_cannot_declare_selected_attempts(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["dataset_selection"]["selected"] = False

        with self.assertRaisesRegex(
            ValueError, "unselected incident cannot declare selected fit attempts"
        ):
            build_fit_validation_dataset_summary(source)

    def test_selected_history_attempt_missing_replay_context_gets_attention(self) -> None:
        source = _load_input(REPEATED_FIXTURE)
        source["fit_incidents"][0]["fit_attempt_history"][0]["user_code_ref"] = None

        summary = build_fit_validation_dataset_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-repeated-attempt",
                    "missing": [
                        ("fit_attempt_history.fit-attempt:rabi-0101-default-failed.user_code_ref")
                    ],
                    "message": ("Selected validation case is missing user-owned replay context."),
                }
            ],
        )

    def test_selected_case_missing_review_note_gets_attention(self) -> None:
        source = _load_input()
        source["fit_incidents"][1]["review_note_ref"] = None

        summary = build_fit_validation_dataset_summary(source)

        self.assertFalse(summary["dataset_draft"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": "incident-rabi-roi-failed",
                    "missing": ["review_note_ref"],
                    "message": ("Selected validation case is missing user-owned replay context."),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
