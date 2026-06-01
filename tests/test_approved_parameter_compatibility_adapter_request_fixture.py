from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "approved_parameter_compatibility_adapter_request"
    / "basic_request"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "request-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-request-summary.json").read_text(encoding="utf-8"))


class ApprovedParameterCompatibilityAdapterRequestFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "request-input.json",
            FIXTURE / "expected-request-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("adapter execution", expected["decisions_not_earned"])
        self.assertIn("stable public adapter API", expected["decisions_not_earned"])
        self.assertIn(
            "adapter owns lab-specific external output generation",
            expected["reference_semantics"]["adapter_boundary"],
        )

    def test_request_is_bound_to_approved_operator_decision(self) -> None:
        source = _input_fixture()
        request = source["adapter_request"]
        approval = source["operator_approval_summary"]

        self.assertEqual(request["approval_id"], approval["operator_decision"]["approval_id"])
        self.assertEqual(
            request["prepared_run_context_id"],
            approval["review_request"]["prepared_run_context_id"],
        )
        self.assertEqual(request["measurement_id"], approval["review_request"]["measurement_id"])
        self.assertEqual(
            request["parameter_state_id"],
            approval["review_request"]["parameter_state_id"],
        )

    def test_expected_summary_has_no_output_or_file_authority(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["classification"], "compatibility_adapter_request_ready_for_external_adapter"
        )
        self.assertEqual(candidate["request_effects"]["adapter_execution"], "not_performed")
        self.assertEqual(candidate["request_effects"]["compatibility_output"], "not_produced")
        self.assertEqual(candidate["request_effects"]["file_write"], "not_performed")
        self.assertEqual(candidate["request_effects"]["external_file_authority"], "not_claimed")


if __name__ == "__main__":
    unittest.main()
