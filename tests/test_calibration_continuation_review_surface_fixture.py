from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_continuation_review_surface" / "basic_surface"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "surface-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-surface-summary.json").read_text(encoding="utf-8"))


class CalibrationContinuationReviewSurfaceFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "surface-input.json",
            FIXTURE / "expected-surface-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_posture(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("GUI workflow", expected["decisions_not_earned"])
        self.assertIn("not a rendered GUI", expected["reference_semantics"]["surface_boundary"])

    def test_input_uses_labels_only_actions(self) -> None:
        source = _input_fixture()

        for card in source["review_state_summary"]["review_cards"]:
            self.assertEqual(card["action_posture"], "labels_only_not_executed")
            self.assertTrue(
                all(isinstance(action, str) for action in card["available_review_actions"])
            )


if __name__ == "__main__":
    unittest.main()
