from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_approval_view_state" / "basic_view"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "view-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-view-summary.json").read_text(encoding="utf-8"))


class PreparedRunApprovalViewStateFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "view-input.json",
            FIXTURE / "expected-view-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("GUI workflow", expected["decisions_not_earned"])
        self.assertIn(
            "compatibility output or compatibility artifact context",
            expected["decisions_not_earned"],
        )
        self.assertIn(
            "canonical context",
            expected["reference_semantics"]["parameter_context_boundary"],
        )

    def test_view_request_is_bound_to_operator_approval(self) -> None:
        source = _input_fixture()
        request = source["view_request"]
        approval = source["operator_approval_summary"]

        self.assertEqual(request["approval_id"], approval["operator_decision"]["approval_id"])
        self.assertEqual(request["review_gate_id"], approval["review_request"]["review_gate_id"])
        self.assertEqual(
            request["prepared_run_context_id"],
            approval["review_request"]["prepared_run_context_id"],
        )
        self.assertEqual(
            request["parameter_state_id"], approval["review_request"]["parameter_state_id"]
        )

    def test_expected_summary_shows_parameter_snapshot_as_context(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["classification"], "prepared_run_approval_view_approved")
        self.assertEqual(
            candidate["review_cards"][0]["context_role"],
            "canonical_parameter_context",
        )
        self.assertEqual(candidate["debug_attachments"]["state"], "omitted")
        self.assertEqual(candidate["view_effects"]["automatic_run_start"], "not_performed")


if __name__ == "__main__":
    unittest.main()
