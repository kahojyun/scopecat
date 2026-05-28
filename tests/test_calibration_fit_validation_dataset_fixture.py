from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "calibration_fit_validation_dataset"
BASIC_FIXTURE = FIXTURE_ROOT / "basic_candidate_queue"
REPEATED_FIXTURE = FIXTURE_ROOT / "repeated_attempt_history"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationFitValidationDatasetFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for fixture in [BASIC_FIXTURE, REPEATED_FIXTURE]:
            for path in [
                fixture / "fit-validation-input.json",
                fixture / "expected-fit-validation-summary.json",
            ]:
                with self.subTest(path=path):
                    _load_json(path)

    def test_input_shape_is_fit_incident_context_not_fit_results_api(self) -> None:
        for path in [
            BASIC_FIXTURE / "fit-validation-input.json",
            REPEATED_FIXTURE / "fit-validation-input.json",
        ]:
            with self.subTest(path=path):
                source = _load_json(path)

                self.assertIn("dataset_draft", source)
                self.assertIn("fit_incidents", source)
                self.assertNotIn("fit_results", source)
                self.assertNotIn("score_contract", source)
                self.assertNotIn("replay_harness", source)

    def test_fixture_covers_recovery_and_curation_cases(self) -> None:
        source = _load_json(BASIC_FIXTURE / "fit-validation-input.json")
        incidents = {incident["incident_id"]: incident for incident in source["fit_incidents"]}

        self.assertEqual(
            incidents["incident-no-signal-resonator"]["state"],
            "no_meaningful_signal",
        )
        self.assertFalse(incidents["incident-no-signal-resonator"]["dataset_selection"]["selected"])
        self.assertEqual(
            incidents["incident-rabi-roi-failed"]["state"],
            "signal_visible_fit_failed",
        )
        self.assertTrue(incidents["incident-rabi-roi-failed"]["dataset_selection"]["selected"])
        self.assertEqual(
            incidents["incident-readout-score-reviewed"]["state"],
            "accepted_after_review",
        )
        self.assertTrue(
            incidents["incident-readout-score-reviewed"]["dataset_selection"]["selected"]
        )

    def test_repeated_attempt_fixture_covers_user_refit_history(self) -> None:
        source = _load_json(REPEATED_FIXTURE / "fit-validation-input.json")
        incident = source["fit_incidents"][0]

        self.assertEqual(incident["state"], "fit_repaired_after_adjustment")
        self.assertEqual(len(incident["fit_attempt_history"]), 2)
        self.assertEqual(
            [attempt["status"] for attempt in incident["fit_attempt_history"]],
            ["fit_failed_exception", "completed_after_user_adjustment"],
        )
        self.assertEqual(
            incident["dataset_selection"]["selected_attempt_ids"],
            [
                "fit-attempt:rabi-0101-default-failed",
                "fit-attempt:rabi-0101-roi-refit-accepted",
            ],
        )

    def test_expected_summary_declares_internal_validation_posture(self) -> None:
        for fixture in [BASIC_FIXTURE, REPEATED_FIXTURE]:
            expected = _load_json(fixture / "expected-fit-validation-summary.json")

            self.assertEqual(expected["status"], "expected_validation_output")
            self.assertEqual(
                expected["reference_semantics"]["artifact_posture"],
                "internal_validation_summary",
            )
            self.assertIn("dataset registry", expected["decisions_not_earned"])
            self.assertIn("hardware control", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
