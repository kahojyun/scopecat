from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_scope_alignment" / "basic_alignment"


def _expected_summary() -> dict:
    return json.loads((FIXTURE / "expected-alignment-summary.json").read_text(encoding="utf-8"))


class PreparedRunScopeAlignmentFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "alignment-input.json",
            FIXTURE / "expected-alignment-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_expected_summary_states_alignment_boundary(self) -> None:
        expected = _expected_summary()
        candidate = expected["candidate_summary"]

        self.assertEqual(expected["summary_policy"], "internal_validation_summary")
        self.assertIn("review projection", expected["reference_semantics"]["contract_guard"])
        self.assertEqual(candidate["alignment_policy"]["hardware_control"], "not_performed")
        self.assertEqual(candidate["alignment_policy"]["parameter_write_back"], "not_performed")
        self.assertEqual(candidate["alignment_policy"]["automatic_run_start"], "not_performed")
        self.assertIn("shared parameter/setup/measurement schema", expected["decisions_not_earned"])

    def test_expected_summary_surfaces_partial_target_coverage(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["classification"], "scope_alignment_needs_review")
        self.assertEqual(candidate["scope_summary"]["setup_sample"]["sample_id"], "sample-alpha")
        self.assertEqual(candidate["scope_summary"]["measurement_logical_targets"], ["qA", "cAB"])
        self.assertIn(
            "parameter_lineage_partial_target_coverage",
            {finding["code"] for finding in candidate["review_findings"]},
        )


if __name__ == "__main__":
    unittest.main()
