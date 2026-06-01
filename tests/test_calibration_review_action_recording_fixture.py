from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_review_action_recording" / "basic_recording"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "action-recording-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-action-recording-summary.json").read_text(encoding="utf-8")
    )


class CalibrationReviewActionRecordingFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "action-recording-input.json",
            FIXTURE / "expected-action-recording-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_posture(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("action execution", expected["decisions_not_earned"])
        self.assertIn(
            "existing surface labels", expected["reference_semantics"]["recording_boundary"]
        )

    def test_events_reference_surface_action_labels(self) -> None:
        source = _input_fixture()
        labels = {
            (item["source"], item["target_id"], item["action_label"])
            for item in source["review_surface_summary"]["action_palette"]
        }

        for event in source["action_events"]:
            key = (event["surface_action_source"], event["target_id"], event["action_label"])
            self.assertIn(key, labels)
            self.assertEqual(event["execution_state"], "not_executed")


if __name__ == "__main__":
    unittest.main()
