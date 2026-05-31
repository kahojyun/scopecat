from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_operator_pre_run_approval" / "basic_approval"


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "approval-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-approval-summary.json").read_text(encoding="utf-8"))


class PreparedRunOperatorPreRunApprovalFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "approval-input.json",
            FIXTURE / "expected-approval-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("automatic run start", expected["decisions_not_earned"])
        self.assertIn("durable storage", expected["decisions_not_earned"])
        self.assertIn(
            "leaves actual run start or execution to later explicit workflow",
            expected["reference_semantics"]["approval_boundary"],
        )

    def test_operator_decision_is_bound_to_review_identity(self) -> None:
        source = _input_fixture()
        decision = source["operator_decision"]
        review_request = source["acknowledgement_aware_review_summary"]["review_request"]

        self.assertEqual(decision["review_gate_id"], review_request["review_gate_id"])
        self.assertEqual(
            decision["prepared_run_context_id"],
            review_request["prepared_run_context_id"],
        )
        self.assertEqual(decision["measurement_id"], review_request["measurement_id"])
        self.assertEqual(decision["parameter_state_id"], review_request["parameter_state_id"])

    def test_expected_summary_records_approval_without_execution_effects(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["classification"], "operator_pre_run_review_approved")
        self.assertEqual(
            candidate["operator_decision"]["approval_state"],
            "operator_approved_review_recorded",
        )
        self.assertEqual(candidate["decision_effects"]["run_start_claim"], "not_claimed")
        self.assertEqual(candidate["decision_effects"]["hardware_control"], "not_performed")
        self.assertEqual(candidate["decision_effects"]["durable_storage"], "not_performed")


if __name__ == "__main__":
    unittest.main()
