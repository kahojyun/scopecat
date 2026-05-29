from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_fit_continuation_composition import (
    build_fit_continuation_composition_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_continuation_composition"
    / "rabi_recovery_with_validation"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "composition-input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict:
    return json.loads((FIXTURE / "expected-composition-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class CalibrationFitContinuationCompositionSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_fit_continuation_composition_summary(_load_input())

        self.assertEqual(summary, _load_expected())
        self.assertNotIn("runner_log", summary)
        self.assertNotIn("fit_results", summary)
        self.assertNotIn("score_contract", summary)
        self.assertNotIn("replay_harness", summary)

    def test_summary_shows_continuation_can_proceed_and_validation_is_preserved(self) -> None:
        summary = build_fit_continuation_composition_summary(_load_input())

        self.assertEqual(summary["continuation_effect"]["status"], "can_continue")
        self.assertFalse(summary["continuation_effect"]["continuation_blocked"])
        self.assertTrue(summary["validation_preservation"]["ready_for_lab_internal_validation"])
        self.assertEqual(
            summary["validation_preservation"]["selected_fit_attempt_refs"],
            [
                "fit-attempt:rabi-05002-default-failed",
                "fit-attempt:rabi-05002-roi-refit-accepted",
            ],
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_fit_continuation_composition_summary(source)

        source["composition_links"]["selected_attempt_ids"].append("mutated")
        source["continuation_input"]["declared_intent"]["target_group"] = "mutated"

        self.assertEqual(
            summary["validation_preservation"]["selected_fit_attempt_refs"],
            [
                "fit-attempt:rabi-05002-default-failed",
                "fit-attempt:rabi-05002-roi-refit-accepted",
            ],
        )
        self.assertEqual(summary["target_group"], "qA")

    def test_missing_linked_step_is_rejected(self) -> None:
        source = _load_input()
        source["composition_links"]["next_step_id"] = "step-missing"

        with self.assertRaisesRegex(ValueError, "composition references missing step"):
            build_fit_continuation_composition_summary(source)

    def test_missing_linked_fit_incident_is_rejected(self) -> None:
        source = _load_input()
        source["composition_links"]["fit_incident_id"] = "incident-missing"

        with self.assertRaisesRegex(ValueError, "composition references missing fit incident"):
            build_fit_continuation_composition_summary(source)

    def test_missing_linked_validation_case_is_rejected(self) -> None:
        source = _load_input()
        source["composition_links"]["validation_case_id"] = "validation-case-missing"

        with self.assertRaisesRegex(ValueError, "composition references missing validation case"):
            build_fit_continuation_composition_summary(source)

    def test_current_step_must_be_completed(self) -> None:
        source = _load_input()
        source["continuation_input"]["observed_records"]["measurements"][1]["produced_by_step"] = (
            "step-unlinked-rabi-output"
        )

        with self.assertRaisesRegex(ValueError, "current step is not completed"):
            build_fit_continuation_composition_summary(source)

    def test_current_and_next_steps_must_differ(self) -> None:
        source = _load_input()
        source["composition_links"]["next_step_id"] = "step-2-rabi-amplitude"

        with self.assertRaisesRegex(ValueError, "current and next steps must differ"):
            build_fit_continuation_composition_summary(source)

    def test_current_step_must_precede_next_step(self) -> None:
        source = _load_input()
        source["composition_links"]["current_step_id"] = "step-3-t1-check"
        source["composition_links"]["next_step_id"] = "step-2-rabi-amplitude"

        with self.assertRaisesRegex(ValueError, "current step must precede next step"):
            build_fit_continuation_composition_summary(source)

    def test_intermediate_steps_must_be_completed(self) -> None:
        source = _load_input()
        source["continuation_input"]["declared_step_plan"].append(
            {
                "planned_step_id": "step-4-final-check",
                "order": 4,
                "label": "Final check",
                "target": "qA",
                "purpose": "Confirm the recovered calibration before ending.",
                "user_authored_entrypoint": "calibration_helpers.final_check",
                "continuation_policy": "requires_prior_steps_completed",
            }
        )
        source["composition_links"]["next_step_id"] = "step-4-final-check"

        with self.assertRaisesRegex(ValueError, "intermediate step is not completed"):
            build_fit_continuation_composition_summary(source)

    def test_recovery_action_must_be_chosen_for_the_linked_incident(self) -> None:
        source = _load_input()
        source["composition_links"]["recovery_action_id"] = (
            "incident-rabi-recovered-for-continuation:adjust_roi_refit"
        )

        with self.assertRaisesRegex(ValueError, "recovery action is not the chosen action"):
            build_fit_continuation_composition_summary(source)

    def test_validation_case_must_belong_to_linked_incident(self) -> None:
        source = _load_input()
        other_incident = copy.deepcopy(source["fit_validation_input"]["fit_incidents"][0])
        other_incident["incident_id"] = "incident-other"
        source["fit_validation_input"]["fit_incidents"].append(other_incident)
        source["composition_links"]["validation_case_id"] = "validation-case-other"

        with self.assertRaisesRegex(ValueError, "validation case belongs to a different incident"):
            build_fit_continuation_composition_summary(source)

    def test_validation_case_measurement_must_be_current_step_output(self) -> None:
        source = _load_input()
        source["fit_validation_input"]["fit_incidents"][0]["measurement_ref"]["record_id"] = (
            "measurement:run-05001"
        )

        with self.assertRaisesRegex(
            ValueError, "validation case measurement is not an output of current step"
        ):
            build_fit_continuation_composition_summary(source)

    def test_validation_case_measurement_must_be_measurement_output(self) -> None:
        source = _load_input()
        source["fit_validation_input"]["fit_incidents"][0]["measurement_ref"]["record_id"] = (
            "fit-preview:rabi-refit-accepted"
        )

        with self.assertRaisesRegex(
            ValueError, "validation case measurement is not a measurement output"
        ):
            build_fit_continuation_composition_summary(source)

    def test_selected_attempts_must_include_current_fit_attempt(self) -> None:
        source = _load_input()
        source["fit_validation_input"]["fit_incidents"][0]["dataset_selection"][
            "selected_attempt_ids"
        ] = ["fit-attempt:rabi-05002-default-failed"]
        source["composition_links"]["selected_attempt_ids"] = [
            "fit-attempt:rabi-05002-default-failed"
        ]

        with self.assertRaisesRegex(ValueError, "selected attempts omit current fit attempt"):
            build_fit_continuation_composition_summary(source)

    def test_selected_attempts_must_match_validation_case(self) -> None:
        source = _load_input()
        source["composition_links"]["selected_attempt_ids"] = [
            "fit-attempt:rabi-05002-default-failed"
        ]

        with self.assertRaisesRegex(ValueError, "selected attempts do not match"):
            build_fit_continuation_composition_summary(source)

    def test_blocked_downstream_step_gets_attention(self) -> None:
        source = _load_input()
        source["continuation_input"]["known_blocking"] = [
            {
                "blocked_step": "step-3-t1-check",
                "blocked_by": ["review:review-resonator-accepted"],
                "reason": "Fixture-declared unresolved review.",
                "authority": "fixture_declared",
            }
        ]
        source["continuation_input"]["known_review_state"] = [
            {
                "review_id": "review-resonator-accepted",
                "related_step": "step-1-resonator-check",
                "status": "needs_user_review",
                "reason_source": "fit-preview:resonator-review",
                "missing_or_unverified": ["user acceptance"],
                "requested_decision": "accept_value_rerun_or_skip_target",
                "authority": "fixture_declared",
            }
        ]
        source["continuation_input"]["observed_records"]["fit_previews"].append(
            {
                "record_id": "fit-preview:resonator-review",
                "related_step": "step-1-resonator-check",
                "source_measurement": "run-05001",
                "label": "Resonator adjusted review preview",
                "path": "artifacts/resonator-review.json",
                "status": "accepted_after_user_adjustment",
                "durable_analysis_result": False,
                "quality_score": 0.9,
                "quality_threshold": 0.8,
                "authority": "fixture_observed_record",
            }
        )
        source["continuation_input"]["observed_records"]["proposed_writes"] = [
            {
                "record_id": "proposed-write:write-qA-readout-frequency",
                "write_id": "write-qA-readout-frequency",
                "related_step": "step-1-resonator-check",
                "status": "proposed_not_applied",
                "parameter_path": "qA.readout.frequency",
                "current_value": 6.1,
                "current_value_source": "snapshot:params-before-step-1",
                "proposed_value": 6.2,
                "proposed_value_source": "fit-preview:resonator-review",
                "unit": "GHz",
                "authority": "user_authored_step_output",
            }
        ]

        summary = build_fit_continuation_composition_summary(source)

        self.assertEqual(summary["continuation_effect"]["status"], "blocked")
        self.assertEqual(
            summary["attention"][0],
            {
                "code": "continuation_still_blocked",
                "subject": "step-3-t1-check",
                "message": "Linked downstream step is still blocked after fit recovery.",
            },
        )

    def test_validation_dataset_not_ready_gets_attention(self) -> None:
        source = _load_input()
        source["fit_validation_input"]["fit_incidents"][0]["review_note_ref"] = None

        summary = build_fit_continuation_composition_summary(source)

        self.assertEqual(summary["continuation_effect"]["status"], "blocked")
        self.assertEqual(
            summary["attention"],
            [
                {
                    "code": "validation_dataset_not_ready",
                    "subject": "fit-validation-dataset-qA-0003",
                    "child_attention": [
                        {
                            "code": "selected_case_missing_replay_context",
                            "subject": "incident-rabi-recovered-for-continuation",
                            "missing": ["review_note_ref"],
                            "message": (
                                "Selected validation case is missing user-owned replay context."
                            ),
                        }
                    ],
                    "message": "Linked validation dataset draft is not ready.",
                }
            ],
        )

    def test_child_summary_validation_errors_are_preserved(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["fit_validation_input"]["fit_incidents"][0])
        source["fit_validation_input"]["fit_incidents"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate incident_id"):
            build_fit_continuation_composition_summary(source)


if __name__ == "__main__":
    unittest.main()
