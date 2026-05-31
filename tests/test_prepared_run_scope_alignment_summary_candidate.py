from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_scope_alignment import (
    build_prepared_run_scope_alignment_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_scope_alignment" / "basic_alignment"


def _load_input() -> dict:
    return json.loads((FIXTURE / "alignment-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-alignment-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunScopeAlignmentSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_scope_alignment_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_scope_alignment_summary(source)

        source["parameter_state_consumption_summary"]["parameter_state"]["lineage"]["target_scope"][
            0
        ] = "mutated"
        source["setup_binding_summary"]["logical_bindings"][0]["logical_entity"] = "mutated"

        self.assertEqual(
            summary["scope_summary"]["parameter_lineage_target_scope"][0], "sample-alpha"
        )
        self.assertEqual(summary["scope_summary"]["bound_logical_entities"], ["cAB", "qA", "qA_ro"])

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["alignment_policy"]["hardware_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_prepared_run_scope_alignment_summary(source)

    def test_consumption_summary_must_not_claim_writeback(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["consumption_policy"][
            "parameter_write_back"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_write_back"):
            build_prepared_run_scope_alignment_summary(source)

    def test_full_target_coverage_is_ready(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["parameter_state"]["lineage"][
            "target_scope"
        ].append("cAB")

        summary = build_prepared_run_scope_alignment_summary(source)

        self.assertEqual(summary["classification"], "scope_alignment_ready")
        self.assertEqual(summary["review_findings"], [])

    def test_missing_setup_binding_target_blocks_review(self) -> None:
        source = _load_input()
        source["setup_binding_summary"]["logical_bindings"] = [
            binding
            for binding in source["setup_binding_summary"]["logical_bindings"]
            if binding["logical_entity"] != "cAB"
        ]

        summary = build_prepared_run_scope_alignment_summary(source)

        self.assertEqual(summary["classification"], "scope_alignment_blocked_for_review")
        self.assertIn(
            "measurement_targets_missing_setup_binding",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_sample_mismatch_blocks_review(self) -> None:
        source = _load_input()
        source["setup_binding_summary"]["setup_bindings"][0]["sample_id"] = "sample-beta"

        summary = build_prepared_run_scope_alignment_summary(source)

        self.assertEqual(summary["classification"], "scope_alignment_blocked_for_review")
        self.assertIn(
            "setup_sample_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_request_must_match_prepared_context(self) -> None:
        source = _load_input()
        source["alignment_request"]["prepared_run_context_id"] = "different-context"

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_scope_alignment_summary(source)

    def test_measurement_input_must_match_setup_binding_request(self) -> None:
        source = _load_input()
        for input_ref in source["setup_binding_summary"]["measurement_references"][0]["inputs"]:
            if input_ref["name"] == "setup_binding":
                input_ref["snapshot_id"] = "setup-binding-other"

        with self.assertRaisesRegex(ValueError, "setup_binding input"):
            build_prepared_run_scope_alignment_summary(source)


if __name__ == "__main__":
    unittest.main()
