from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_fit_recovery_workflow"
    / "no_signal_and_visible_refit"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationFitRecoveryWorkflowFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "recovery-workflow-input.json",
            FIXTURE / "expected-recovery-workflow-summary.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_fixture_stays_inside_recovery_workflow_boundary(self) -> None:
        source = _load_json(FIXTURE / "recovery-workflow-input.json")

        self.assertIn("fit_recovery_incidents", source)
        self.assertIn("dataset_draft", source)
        self.assertNotIn("runner_log", source)
        self.assertNotIn("fit_results", source)
        self.assertNotIn("score_contract", source)
        self.assertNotIn("replay_harness", source)
        self.assertNotIn("dataset_registry", source)
        self.assertNotIn("hardware_session", source)

    def test_fixture_covers_no_signal_and_visible_signal_recovery(self) -> None:
        source = _load_json(FIXTURE / "recovery-workflow-input.json")
        incidents = {
            incident["incident_id"]: incident for incident in source["fit_recovery_incidents"]
        }

        self.assertEqual(
            incidents["incident-no-signal-readout-06001"]["signal_assessment"]["classification"],
            "no_clear_signal",
        )
        self.assertFalse(
            incidents["incident-no-signal-readout-06001"]["dataset_selection"]["selected"]
        )
        self.assertEqual(
            incidents["incident-rabi-visible-refit-06002"]["signal_assessment"]["classification"],
            "visible_signal",
        )
        self.assertTrue(
            incidents["incident-rabi-visible-refit-06002"]["dataset_selection"]["selected"]
        )

    def test_expected_summary_declares_internal_validation_posture(self) -> None:
        expected = _load_json(FIXTURE / "expected-recovery-workflow-summary.json")

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["reference_semantics"]["artifact_posture"],
            "internal_validation_summary",
        )
        self.assertIn("replay harness", expected["decisions_not_earned"])
        self.assertIn("dataset registry", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
