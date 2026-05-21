from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.calibration_work_continuation import (
    build_calibration_continuation_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_work_continuation" / "review_gate_failed_fit"


def _load_input() -> dict:
    return json.loads((FIXTURE / "continuation-input.json").read_text(encoding="utf-8"))


class CalibrationWorkContinuationSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_calibration_continuation_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-continuation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_lifecycle_state_is_assembled_from_context(self) -> None:
        summary = build_calibration_continuation_summary(_load_input())
        steps = {step["step_id"]: step for step in summary["steps"]}

        self.assertEqual(steps["step-1-resonator-check"]["lifecycle_state"], "completed")
        self.assertEqual(
            steps["step-1-resonator-check"]["lifecycle_source"],
            "assembled_from_observed_records",
        )
        self.assertEqual(steps["step-2-rabi-amplitude"]["lifecycle_state"], "review_needed")
        self.assertEqual(
            steps["step-2-rabi-amplitude"]["lifecycle_source"],
            "assembled_from_known_review_state",
        )
        self.assertEqual(steps["step-3-t1-check"]["lifecycle_state"], "blocked")
        self.assertEqual(
            steps["step-3-t1-check"]["lifecycle_source"],
            "assembled_from_known_blocking",
        )

    def test_attention_is_derived_from_lower_level_facts(self) -> None:
        source = _load_input()
        source["observed_records"]["fit_previews"][0]["quality_score"] = 0.95
        source["observed_records"]["fit_previews"][0]["status"] = "passed_quality_review"
        source["observed_records"]["proposed_writes"][0]["status"] = "applied_outside_scopecat"
        source["known_blocking"] = []

        summary = build_calibration_continuation_summary(source)

        self.assertEqual(summary["attention"], [])

    def test_requested_actions_follow_review_and_blocking_state(self) -> None:
        source = _load_input()
        source["known_blocking"] = []

        summary = build_calibration_continuation_summary(source)
        action_ids = [action["action_id"] for action in summary["requested_next_actions"]]
        actions = {action["action_id"]: action for action in summary["requested_next_actions"]}

        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertTrue(actions["review-review-rabi-04002"]["available"])
        self.assertTrue(actions["accept-write-qA-pulse-amplitude-outside-scopecat"]["available"])
        self.assertTrue(actions["rerun-step-2-rabi-amplitude"]["available"])
        self.assertTrue(actions["skip-qA-for-review-rabi-04002"]["available"])
        self.assertNotIn("continue-step-3-t1-check", actions)

    def test_requested_actions_are_assembled_from_fixture_terms(self) -> None:
        source = _load_input()
        source["declared_step_plan"][1]["label"] = "Amplitude decision"
        source["declared_step_plan"][1]["target"] = "qB"
        source["observed_records"]["proposed_writes"][0]["parameter_path"] = "qB.pulse.amplitude"

        summary = build_calibration_continuation_summary(source)
        actions = {action["action_id"]: action for action in summary["requested_next_actions"]}

        self.assertIn("skip-qB-for-review-rabi-04002", actions)
        self.assertEqual(
            actions["rerun-step-2-rabi-amplitude"]["label"], "Rerun Amplitude decision"
        )
        self.assertEqual(
            actions["accept-write-qA-pulse-amplitude-outside-scopecat"]["label"],
            "Accept proposed qB.pulse.amplitude outside Scopecat after review",
        )

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_calibration_continuation_summary(source)

        source["declared_intent"]["execution_context"]["label"] = "mutated"
        source["observed_records"]["fit_previews"][0]["quality_score"] = 0.1

        self.assertEqual(
            summary["episode"]["execution_context"]["label"],
            "notebook-like local session",
        )
        fit_output = next(
            output
            for output in summary["outputs"]
            if output["output_id"] == "fit-preview:rabi-fit-preview-failed-quality"
        )
        self.assertEqual(fit_output["quality_score"], 0.58)

    def test_duplicate_review_steps_are_rejected(self) -> None:
        source = _load_input()
        duplicate = copy.deepcopy(source["known_review_state"][0])
        duplicate["review_id"] = "review-rabi-04002-duplicate"
        source["known_review_state"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "duplicate related_step"):
            build_calibration_continuation_summary(source)

    def test_missing_review_reason_source_is_rejected(self) -> None:
        source = _load_input()
        source["known_review_state"][0]["reason_source"] = "fit-preview:missing"

        with self.assertRaisesRegex(ValueError, "review references missing reason_source"):
            build_calibration_continuation_summary(source)

    def test_blocking_must_reference_existing_review(self) -> None:
        source = _load_input()
        source["known_blocking"][0]["blocked_by"] = ["review:missing-review"]

        with self.assertRaisesRegex(ValueError, "blocking references missing review"):
            build_calibration_continuation_summary(source)

    def test_proposed_write_sources_must_reference_observed_records(self) -> None:
        source = _load_input()
        source["observed_records"]["proposed_writes"][0]["current_value_source"] = (
            "snapshot:missing"
        )

        with self.assertRaisesRegex(
            ValueError, "proposed write references missing current_value_source"
        ):
            build_calibration_continuation_summary(source)

    def test_failed_quality_review_must_be_below_threshold(self) -> None:
        source = _load_input()
        source["observed_records"]["fit_previews"][0]["quality_score"] = 0.8

        with self.assertRaisesRegex(
            ValueError, "failed quality review source is not below threshold"
        ):
            build_calibration_continuation_summary(source)


if __name__ == "__main__":
    unittest.main()
