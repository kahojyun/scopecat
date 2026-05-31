from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_parameter_state_gate" / "basic_gate"


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-gate-summary.json").read_text(encoding="utf-8"))


class PreparedRunParameterStateGateFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "gate-input.json",
            FIXTURE / "expected-gate-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_gate_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn(
            "parameter-context review gate",
            expected["reference_semantics"]["contract_guard"],
        )
        self.assertEqual(candidate["gate_policy"]["automatic_run_start"], "not_performed")
        self.assertEqual(candidate["gate_policy"]["parameter_write_back"], "not_performed")
        self.assertEqual(candidate["gate_policy"]["hardware_control"], "not_performed")
        self.assertIn("automatic run start", expected["decisions_not_earned"])

    def test_expected_summary_is_ready_for_manual_review_only(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["gate_decision"]["gate_state"],
            "ready_for_manual_run_review",
        )
        self.assertEqual(candidate["gate_decision"]["run_start_claim"], "not_claimed")
        self.assertEqual(candidate["parameter_state_gate_input"]["trusted_entry_count"], 2)
        self.assertEqual(candidate["review_findings"], [])


if __name__ == "__main__":
    unittest.main()
