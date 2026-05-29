from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_continuation_route_shape"
    / "minimum_contract_with_degraded_context"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CalibrationContinuationRouteShapeFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "route-shape-input.json",
            FIXTURE / "expected-route-shape-summary.json",
        ]:
            with self.subTest(path=path):
                _load_json(path)

    def test_fixture_stays_inside_route_shape_boundary(self) -> None:
        source = _load_json(FIXTURE / "route-shape-input.json")

        self.assertIn("route_input_contract_summary", source)
        self.assertIn("route_shape", source)
        self.assertNotIn("gui_component", source)
        self.assertNotIn("notebook_execution", source)
        self.assertNotIn("runner_log", source)
        self.assertNotIn("fit_results", source)
        self.assertNotIn("measurement_payload", source)
        self.assertNotIn("reference_payloads", source)
        self.assertNotIn("parameter_write", source)
        self.assertNotIn("hardware_session", source)
        self.assertNotIn("dataset_package", source)
        self.assertNotIn("lab_sharing_bundle", source)

    def test_expected_summary_declares_internal_validation_posture(self) -> None:
        expected = _load_json(FIXTURE / "expected-route-shape-summary.json")

        self.assertEqual(expected["status"], "expected_validation_output")
        self.assertEqual(
            expected["reference_semantics"]["artifact_posture"],
            "internal_validation_summary",
        )
        self.assertIn("GUI implementation", expected["decisions_not_earned"])
        self.assertIn("dataset registry", expected["decisions_not_earned"])
        self.assertIn("hardware control", expected["decisions_not_earned"])


if __name__ == "__main__":
    unittest.main()
