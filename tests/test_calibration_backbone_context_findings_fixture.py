from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "calibration_backbone_context_findings" / "basic_pressure"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "backbone-findings-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-backbone-findings-summary.json").read_text(encoding="utf-8")
    )


class CalibrationBackboneContextFindingsFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "backbone-findings-input.json",
            FIXTURE / "expected-backbone-findings-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_posture(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("shared route schema", expected["decisions_not_earned"])
        self.assertIn(
            "not measurement invalidity",
            expected["reference_semantics"]["measurement_context_posture"],
        )

    def test_fixture_covers_ready_blocked_and_review_cases(self) -> None:
        case_ids = {case["case_id"] for case in _input_fixture()["backbone_cases"]}

        self.assertIn("ready-backbone", case_ids)
        self.assertIn("intake-unavailable", case_ids)
        self.assertIn("measurement-link-missing", case_ids)


if __name__ == "__main__":
    unittest.main()
