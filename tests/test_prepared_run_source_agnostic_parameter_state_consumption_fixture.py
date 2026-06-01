from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prepared_run_source_agnostic_parameter_state_consumption"
    / "basic_consumption"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "consumption-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-consumption-summary.json").read_text(encoding="utf-8"))


class PreparedRunSourceAgnosticParameterStateConsumptionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "consumption-input.json",
            FIXTURE / "expected-consumption-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("universal provenance schema", expected["decisions_not_earned"])

    def test_input_selects_calibration_derived_parameter_state(self) -> None:
        source = _input_fixture()

        self.assertEqual(source["consumption_request"]["expected_state_id"], "param-state-0008")
        self.assertEqual(
            source["consumption_policy"]["parameter_state_source"],
            "source_agnostic_storage_read_view_summary",
        )

    def test_expected_summary_carries_typed_calibration_provenance(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["parameter_state"]["source_kind"], "calibration_handoff")
        self.assertEqual(
            candidate["typed_provenance"]["payload"]["source_observation"],
            "validated_calibration_handoff_summary",
        )
        self.assertEqual(
            candidate["typed_provenance"]["source_handoff"]["apply_state"], "not_applied"
        )

    def test_no_execution_or_hardware_claims(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["consumption_policy"]["fresh_storage_read"], "not_performed")
        self.assertEqual(candidate["consumption_policy"]["parameter_write_back"], "not_performed")
        self.assertEqual(candidate["consumption_policy"]["hardware_control"], "not_performed")


if __name__ == "__main__":
    unittest.main()
