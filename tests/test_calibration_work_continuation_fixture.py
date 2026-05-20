from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_work_continuation" / "review_gate_failed_fit"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationWorkContinuationFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "continuation-input.json",
            FIXTURE / "expected-continuation-summary.json",
            FIXTURE / "snapshots" / "params-before-step-1.json",
            FIXTURE / "snapshots" / "params-before-step-2.json",
            FIXTURE / "artifacts" / "fit-rabi-04002.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_expected_summary_has_wrapper_and_candidate_summary(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        candidate = summary["candidate_summary"]

        self.assertEqual(summary["status"], "expected_validation_output")
        self.assertEqual(
            summary["reference_semantics"]["status"],
            "fixture_paths_are_package_relative",
        )
        self.assertEqual(candidate["episode"]["episode_id"], "cal-episode-04001")
        self.assertEqual(candidate["episode"]["target_group"], "qA")
        self.assertEqual(
            candidate["episode"]["execution_context"]["kind"],
            "local_user_python",
        )

    def test_input_shape_is_scattered_context_not_runner_log(self) -> None:
        source = _load_json(FIXTURE / "continuation-input.json")

        self.assertIn("declared_intent", source)
        self.assertIn("declared_step_plan", source)
        self.assertIn("observed_records", source)
        self.assertIn("known_review_state", source)
        self.assertIn("known_blocking", source)
        self.assertNotIn("steps", source)
        self.assertNotIn("outputs", source)
        self.assertNotIn("review_gates", source)
        self.assertNotIn("requested_next_actions", source)
        self.assertNotIn("attention_expected", source)

    def test_step_states_capture_review_and_blocking(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        steps = {step["step_id"]: step for step in summary["candidate_summary"]["steps"]}

        self.assertEqual(steps["step-1-resonator-check"]["lifecycle_state"], "completed")
        self.assertEqual(steps["step-2-rabi-amplitude"]["lifecycle_state"], "review_needed")
        self.assertEqual(steps["step-3-t1-check"]["lifecycle_state"], "blocked")
        self.assertEqual(
            steps["step-3-t1-check"]["blocked_by"],
            ["review:review-rabi-04002"],
        )
        self.assertEqual(
            steps["step-1-resonator-check"]["lifecycle_source"],
            "assembled_from_observed_records",
        )
        self.assertEqual(
            steps["step-2-rabi-amplitude"]["lifecycle_source"],
            "assembled_from_known_review_state",
        )
        self.assertEqual(
            steps["step-3-t1-check"]["lifecycle_source"],
            "assembled_from_known_blocking",
        )

    def test_outputs_preserve_observed_record_authority_and_fit_evidence(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        outputs = {
            output["output_id"]: output for output in summary["candidate_summary"]["outputs"]
        }

        self.assertEqual(
            outputs["measurement:run-04001"]["authority"],
            "fixture_observed_record",
        )
        self.assertEqual(
            outputs["fit-preview:fit-rabi-04002"]["authority"],
            "fixture_observed_record",
        )
        self.assertEqual(outputs["fit-preview:fit-rabi-04002"]["quality_score"], 0.58)
        self.assertEqual(outputs["fit-preview:fit-rabi-04002"]["quality_threshold"], 0.8)

    def test_declared_write_is_proposed_not_applied(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        writes = summary["candidate_summary"]["declared_writes"]

        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["status"], "proposed_not_applied")
        self.assertEqual(writes[0]["authority"], "user_authored_step_output")
        self.assertEqual(writes[0]["requires_review"], "review-rabi-04002")
        self.assertEqual(summary["candidate_summary"]["applied_writes"], [])

    def test_attention_codes_follow_lower_level_facts(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        candidate = summary["candidate_summary"]
        fit_preview = next(
            output
            for output in candidate["outputs"]
            if output["output_id"] == "fit-preview:fit-rabi-04002"
        )
        blocked_step = next(
            step for step in candidate["steps"] if step["step_id"] == "step-3-t1-check"
        )
        proposed_write = candidate["declared_writes"][0]

        self.assertEqual(fit_preview["status"], "failed_quality_review")
        self.assertLess(fit_preview["quality_score"], fit_preview["quality_threshold"])
        self.assertEqual(blocked_step["lifecycle_state"], "blocked")
        self.assertEqual(proposed_write["status"], "proposed_not_applied")
        self.assertEqual(
            [attention["code"] for attention in candidate["attention"]],
            [
                "fit_failed_quality_review",
                "downstream_step_blocked",
                "write_requires_review",
            ],
        )

    def test_output_paths_are_openable(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        outputs = summary["candidate_summary"]["outputs"]

        for output in outputs:
            with self.subTest(output=output["output_id"]):
                self.assertTrue((FIXTURE / output["path"]).exists())

    def test_fixture_write_values_match_snapshot_and_fit_artifact(self) -> None:
        source = _load_json(FIXTURE / "continuation-input.json")
        proposed_write = source["observed_records"]["proposed_writes"][0]
        records = {
            record["record_id"]: record
            for group in source["observed_records"].values()
            if isinstance(group, list)
            for record in group
            if isinstance(record, dict) and "record_id" in record
        }
        snapshot = _load_json(FIXTURE / records[proposed_write["current_value_source"]]["path"])
        fit_artifact = _load_json(
            FIXTURE / records[proposed_write["proposed_value_source"]]["path"]
        )

        self.assertEqual(
            proposed_write["current_value"],
            snapshot["parameters"][proposed_write["parameter_path"]],
        )
        self.assertEqual(
            proposed_write["proposed_value"],
            fit_artifact["estimated_amplitude"],
        )

    def test_fixture_fit_preview_matches_artifact_evidence(self) -> None:
        source = _load_json(FIXTURE / "continuation-input.json")
        fit_preview = source["observed_records"]["fit_previews"][0]
        artifact = _load_json(FIXTURE / fit_preview["path"])

        self.assertEqual(fit_preview["source_measurement"], artifact["source_measurement"])
        self.assertEqual(fit_preview["status"], artifact["status"])
        self.assertEqual(fit_preview["quality_score"], artifact["quality_score"])
        self.assertEqual(fit_preview["quality_threshold"], artifact["quality_threshold"])
        self.assertEqual(
            fit_preview["durable_analysis_result"],
            artifact["durable_analysis_result"],
        )

    def test_requested_next_actions_do_not_autonomously_continue(self) -> None:
        summary = _load_json(FIXTURE / "expected-continuation-summary.json")
        actions = {
            action["action_id"]: action
            for action in summary["candidate_summary"]["requested_next_actions"]
        }

        self.assertTrue(actions["review-review-rabi-04002"]["available"])
        self.assertTrue(actions["accept-write-qA-pulse-amplitude-outside-scopecat"]["available"])
        self.assertTrue(actions["rerun-step-2-rabi-amplitude"]["available"])
        self.assertTrue(actions["skip-qA-for-review-rabi-04002"]["available"])
        self.assertFalse(actions["continue-step-3-t1-check"]["available"])
        self.assertEqual(
            actions["continue-step-3-t1-check"]["blocked_by"],
            ["review:review-rabi-04002"],
        )

    def test_review_states_calibration_specific_boundary(self) -> None:
        review = (FIXTURE / "expected-continuation-review.md").read_text(encoding="utf-8")

        self.assertIn("Fixture Wrapper", review)
        self.assertIn("Candidate Summary Review", review)
        self.assertIn("calibration-specific step state", review)
        self.assertIn("not a Scopecat-decided mutation", review)
        self.assertIn("state-only; it does not execute fixture code", review)
        self.assertIn("scattered continuation", review)
        self.assertIn("authoring model or executor input contract", review)
        self.assertIn("episode/step/review model is not earned", review)
        self.assertIn("ordinary calibration-continuation state", review)


if __name__ == "__main__":
    unittest.main()
