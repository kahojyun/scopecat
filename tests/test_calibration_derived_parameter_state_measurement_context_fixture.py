from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "calibration_derived_parameter_state_measurement_context"
    / "basic_chain"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "route-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-route-summary.json").read_text(encoding="utf-8"))


class CalibrationDerivedParameterStateMeasurementContextFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "route-input.json",
            FIXTURE / "expected-route-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_internal_validation_posture(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("durable relation graph", expected["decisions_not_earned"])
        self.assertIn(
            "managed parameter-state snapshot",
            expected["reference_semantics"]["canonical_parameter_context"],
        )

    def test_input_links_later_measurement_to_selected_parameter_state(self) -> None:
        source = _input_fixture()
        selected_ref = source["prepared_run_context_summary"]["selected_context_refs"][1]
        linked_ref = source["measurement_context_link_summary"]["linked_context_refs"][0]

        self.assertEqual(selected_ref["family"], "parameter_state")
        self.assertEqual(selected_ref["context_id"], "param-state-0008")
        self.assertEqual(linked_ref["measurement_record_id"], "measurement-05001")
        self.assertEqual(linked_ref["context_id"], selected_ref["context_id"])
        self.assertFalse(linked_ref["required_for_record_validity"])


if __name__ == "__main__":
    unittest.main()
