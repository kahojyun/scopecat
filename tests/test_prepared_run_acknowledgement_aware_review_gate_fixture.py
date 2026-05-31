from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "prepared_run_acknowledgement_aware_review_gate" / "basic_ready"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "review-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-review-summary.json").read_text(encoding="utf-8"))


class PreparedRunAcknowledgementAwareReviewGateFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "review-input.json",
            FIXTURE / "expected-review-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("run-start permission", expected["decisions_not_earned"])
        self.assertIn("compatibility output", expected["decisions_not_earned"])
        self.assertIn(
            "not that a run may start automatically",
            expected["reference_semantics"]["operator_decision_boundary"],
        )

    def test_input_binds_request_to_acknowledged_context_and_state(self) -> None:
        source = _input_fixture()
        request = source["review_request"]
        acknowledgement = source["partial_target_acknowledgement_summary"]

        self.assertEqual(
            request["prepared_run_context_id"],
            acknowledgement["prepared_run_context"]["prepared_run_context_id"],
        )
        self.assertEqual(
            request["measurement_id"], acknowledgement["prepared_run_context"]["measurement_id"]
        )
        self.assertEqual(
            request["parameter_state_id"],
            acknowledgement["selected_parameter_state"]["state_id"],
        )

    def test_expected_summary_clears_only_acknowledged_finding(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["gate_decision"]["overall_state"],
            "ready_for_operator_pre_run_decision",
        )
        self.assertEqual(candidate["remaining_acknowledgement_findings"], [])
        self.assertEqual(candidate["manual_review_findings"], [])
        self.assertEqual(
            candidate["acknowledged_review_findings"][0]["code"],
            "parameter_lineage_partial_target_coverage",
        )


if __name__ == "__main__":
    unittest.main()
