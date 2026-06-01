from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_source_agnostic_parameter_state_review_chain import (
    build_prepared_run_source_agnostic_parameter_state_review_chain_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prepared_run_source_agnostic_parameter_state_review_chain"
    / "basic_chain"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-chain-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-review-chain-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunSourceAgnosticParameterStateReviewChainSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(
            _load_input()
        )

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

        source["source_agnostic_consumption_summary"]["parameter_state"]["state_id"] = "mutated"
        source["scope_alignment_input"]["setup_binding_summary"]["logical_bindings"][0][
            "logical_entity"
        ] = "mutated"

        self.assertEqual(summary["selected_parameter_state"]["state_id"], "param-state-0008")
        self.assertEqual(
            summary["scope_alignment_summary"]["scope_summary"]["bound_logical_entities"],
            ["cAB", "qA", "qA_ro"],
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["review_chain_policy"]["fresh_storage_read"] = "performed"

        with self.assertRaisesRegex(ValueError, "fresh_storage_read"):
            build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

    def test_consumption_must_be_source_agnostic(self) -> None:
        source = _load_input()
        source["source_agnostic_consumption_summary"]["consumption_policy"][
            "parameter_state_source"
        ] = "explicit_storage_read_view_summary"

        with self.assertRaisesRegex(ValueError, "source-agnostic"):
            build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

    def test_first_fixture_requires_calibration_handoff_source(self) -> None:
        source = _load_input()
        source["source_agnostic_consumption_summary"]["parameter_state"]["source_kind"] = (
            "adapter_import"
        )

        with self.assertRaisesRegex(ValueError, "calibration_handoff"):
            build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

    def test_gate_input_must_use_consumption_summary_unchanged(self) -> None:
        source = _load_input()
        source["gate_input"]["parameter_state_consumption_summary"] = copy.deepcopy(
            source["source_agnostic_consumption_summary"]
        )
        source["gate_input"]["parameter_state_consumption_summary"]["parameter_state"][
            "state_id"
        ] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "gate input"):
            build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

    def test_alignment_input_must_use_consumption_summary_unchanged(self) -> None:
        source = _load_input()
        source["scope_alignment_input"]["parameter_state_consumption_summary"] = copy.deepcopy(
            source["source_agnostic_consumption_summary"]
        )
        source["scope_alignment_input"]["parameter_state_consumption_summary"]["classification"] = (
            "prepared_run_parameter_state_needs_review"
        )

        with self.assertRaisesRegex(ValueError, "scope alignment input"):
            build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

    def test_gate_findings_make_chain_need_review(self) -> None:
        source = _load_input()
        source["gate_input"]["gate_request"]["required_min_trusted_entries"] = 3

        summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

        self.assertEqual(summary["classification"], "parameter_review_chain_needs_review")
        self.assertIn(
            "insufficient_trusted_entries",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_scope_blocking_makes_chain_blocked(self) -> None:
        source = _load_input()
        source["scope_alignment_input"]["setup_binding_summary"]["setup_bindings"][0][
            "sample_id"
        ] = "sample-beta"

        summary = build_prepared_run_source_agnostic_parameter_state_review_chain_summary(source)

        self.assertEqual(summary["classification"], "parameter_review_chain_blocked")
        self.assertIn(
            "setup_sample_mismatch",
            {finding["code"] for finding in summary["review_findings"]},
        )


if __name__ == "__main__":
    unittest.main()
