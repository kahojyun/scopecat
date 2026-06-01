from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prepared_run_partial_target_acknowledgement"
    / "basic_acknowledgement"
)


def _input_fixture() -> dict:
    return json.loads((FIXTURE / "acknowledgement-input.json").read_text(encoding="utf-8"))


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-acknowledgement-summary.json").read_text(encoding="utf-8")
    )


class PreparedRunPartialTargetAcknowledgementFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "acknowledgement-input.json",
            FIXTURE / "expected-acknowledgement-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_declares_internal_validation_boundary(self) -> None:
        expected = _expected_summary()

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("automatic run start", expected["decisions_not_earned"])
        self.assertIn("setup mutation", expected["decisions_not_earned"])
        self.assertIn(
            "leaves all execution authority out of scope",
            expected["reference_semantics"]["acknowledgement_boundary"],
        )

    def test_acknowledgement_is_bound_to_review_chain_identity(self) -> None:
        source = _input_fixture()
        acknowledgement = source["user_acknowledgement"]
        chain = source["review_chain_summary"]

        self.assertEqual(
            acknowledgement["prepared_run_context_id"],
            chain["prepared_run_context"]["prepared_run_context_id"],
        )
        self.assertEqual(
            acknowledgement["parameter_state_id"],
            chain["selected_parameter_state"]["state_id"],
        )

    def test_expected_summary_preserves_exact_finding_basis(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(
            candidate["acknowledged_finding"]["basis"],
            {
                "covered_targets": ["qA"],
                "missing_targets": ["cAB"],
            },
        )
        self.assertEqual(candidate["remaining_review_findings"], [])
        self.assertEqual(
            candidate["downstream_review_state"]["run_start_claim"],
            "not_claimed",
        )


if __name__ == "__main__":
    unittest.main()
