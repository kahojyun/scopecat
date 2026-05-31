from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "prepared_run_parameter_state_consumption" / "basic_consumption"
)


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-consumption-summary.json").read_text(encoding="utf-8"))


class PreparedRunParameterStateConsumptionFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "consumption-input.json",
            FIXTURE / "expected-consumption-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_composition_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn(
            "composition of declared prepared-run context",
            expected["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(candidate["consumption_policy"]["fresh_storage_read"], "not_performed")
        self.assertEqual(candidate["consumption_policy"]["catalog_discovery"], "not_performed")
        self.assertEqual(candidate["consumption_policy"]["parameter_write_back"], "not_performed")
        self.assertIn("automatic run blocking", expected["decisions_not_earned"])

    def test_expected_summary_projects_trusted_entries_and_storage_facts(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["classification"], "prepared_run_parameter_state_ready")
        self.assertEqual(candidate["parameter_state"]["state_id"], "param-state-imported-0001")
        self.assertEqual(
            [entry["path"] for entry in candidate["trusted_entries"]],
            ["qubits.qA.drive_frequency_hz", "qubits.qA.pi_amp"],
        )
        self.assertEqual(candidate["storage_read_facts"]["manifest"]["observed_size_bytes"], 3563)
        self.assertEqual(candidate["storage_read_facts"]["receipt"]["observed_size_bytes"], 640)


if __name__ == "__main__":
    unittest.main()
