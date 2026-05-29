from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_recovery_interaction_recording"
    / "no_signal_and_visible_refit_events"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationFitRecoveryInteractionRecordingFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "interaction-recording-input.json",
            FIXTURE / "expected-interaction-recording-summary.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_fixture_stays_inside_interaction_recording_boundary(self) -> None:
        source = _load_json(FIXTURE / "interaction-recording-input.json")

        self.assertIn("interaction_events", source)
        self.assertIn("workflow_input_before", source)
        self.assertIn("review_surface", source)
        self.assertNotIn("gui_event_log", source)
        self.assertNotIn("notebook_execution", source)
        self.assertNotIn("runner_log", source)
        self.assertNotIn("fit_results", source)
        self.assertNotIn("score_contract", source)
        self.assertNotIn("replay_harness", source)
        self.assertNotIn("dataset_registry", source)
        self.assertNotIn("hardware_session", source)

    def test_expected_summary_declares_internal_validation_posture(self) -> None:
        expected = _load_json(FIXTURE / "expected-interaction-recording-summary.json")

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["reference_semantics"]["artifact_posture"],
            "internal_validation_summary",
        )
        self.assertIn("GUI implementation", expected["decisions_not_earned"])
        self.assertIn("notebook integration", expected["decisions_not_earned"])
        self.assertIn("portable/public dataset package", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
