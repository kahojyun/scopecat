from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prepared_run_source_agnostic_parameter_state_review_chain"
    / "basic_chain"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "review-chain-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-review-chain-summary.json").read_text(encoding="utf-8"))


class PreparedRunSourceAgnosticParameterStateReviewChainFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "review-chain-input.json",
            FIXTURE / "expected-review-chain-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_declares_existing_schema_reuse(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("new gate schema", expected["decisions_not_earned"])
        self.assertIn("reused unchanged", expected["reference_semantics"]["reuse_boundary"])

    def test_input_uses_source_agnostic_consumption_for_gate_and_alignment(self) -> None:
        source = _input_fixture()
        consumption = source["source_agnostic_consumption_summary"]

        self.assertEqual(source["gate_input"]["parameter_state_consumption_summary"], consumption)
        self.assertEqual(
            source["scope_alignment_input"]["parameter_state_consumption_summary"],
            consumption,
        )

    def test_expected_summary_proves_gate_reuse_and_scope_review(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["gate_summary"]["gate_decision"]["gate_state"],
            "ready_for_manual_run_review",
        )
        self.assertEqual(
            candidate["scope_alignment_summary"]["classification"],
            "scope_alignment_needs_review",
        )
        self.assertIn(
            "parameter_lineage_partial_target_coverage",
            {finding["code"] for finding in candidate["review_findings"]},
        )


if __name__ == "__main__":
    unittest.main()
