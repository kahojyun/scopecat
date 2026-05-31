from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_review_gate" / "basic_gate"


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-review-gate-summary.json").read_text(encoding="utf-8"))


class PreparedRunReviewGateFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "review-gate-input.json",
            FIXTURE / "expected-review-gate-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_manual_review_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("manual pre-run review", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["review_gate_policy"]["automatic_run_start"], "not_performed")
        self.assertEqual(candidate["review_gate_policy"]["hardware_control"], "not_performed")
        self.assertEqual(candidate["review_gate_policy"]["dependency_sync"], "not_performed")
        self.assertIn("run-start permission", expected["decisions_not_earned"])

    def test_expected_summary_aggregates_review_areas(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        states = {item["area"]: item["state"] for item in candidate["review_items"]}

        self.assertEqual(candidate["gate_decision"]["overall_state"], "blocked_by_required_context")
        self.assertEqual(states["required_context"], "blocked_by_required_context")
        self.assertEqual(states["parameter_state"], "ready_for_manual_review")
        self.assertEqual(states["scope_alignment"], "needs_scope_review")
        self.assertEqual(states["workspace"], "needs_workspace_review")
        self.assertEqual(states["environment"], "needs_environment_review")


if __name__ == "__main__":
    unittest.main()
