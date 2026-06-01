from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_partial_target_acknowledgement import (
    build_prepared_run_partial_target_acknowledgement_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prepared_run_partial_target_acknowledgement"
    / "basic_acknowledgement"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "acknowledgement-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads(
        (FIXTURE / "expected-acknowledgement-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


class PreparedRunPartialTargetAcknowledgementSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_partial_target_acknowledgement_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_partial_target_acknowledgement_summary(source)

        source["review_chain_summary"]["prepared_run_context"]["logical_targets"].append("mutated")
        source["review_chain_summary"]["review_findings"][0]["basis"]["missing_targets"].append(
            "mutated"
        )

        self.assertEqual(summary["prepared_run_context"]["logical_targets"], ["qA", "cAB"])
        self.assertEqual(
            summary["acknowledged_finding"]["basis"],
            {"covered_targets": ["qA"], "missing_targets": ["cAB"]},
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["acknowledgement_policy"]["hardware_control"] = "performed"

        with self.assertRaisesRegex(ValueError, "hardware_control"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_acknowledgement_must_match_exact_finding_basis(self) -> None:
        source = _load_input()
        source["user_acknowledgement"]["finding_basis"] = {
            "covered_targets": ["qA", "cAB"],
            "missing_targets": [],
        }

        with self.assertRaisesRegex(ValueError, "exactly one partial target finding"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_acknowledgement_must_match_prepared_run_context(self) -> None:
        source = _load_input()
        source["user_acknowledgement"]["prepared_run_context_id"] = "other-context"

        with self.assertRaisesRegex(ValueError, "prepared run context"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_acknowledgement_must_match_parameter_state(self) -> None:
        source = _load_input()
        source["user_acknowledgement"]["parameter_state_id"] = "param-state-other"

        with self.assertRaisesRegex(ValueError, "parameter state"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_unsupported_decision_is_rejected(self) -> None:
        source = _load_input()
        source["user_acknowledgement"]["decision"] = "approved_to_run"

        with self.assertRaisesRegex(ValueError, "unsupported"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_side_effect_claims_must_remain_non_mutating(self) -> None:
        source = _load_input()
        source["side_effect_claims"]["setup_mutation"] = "performed"

        with self.assertRaisesRegex(ValueError, "setup_mutation"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

    def test_unacknowledged_review_findings_remain_visible(self) -> None:
        source = _load_input()
        source["review_chain_summary"]["review_findings"].append(
            {
                "source": "parameter_gate",
                "code": "manual_parameter_context_note",
                "severity": "review",
                "basis": {"note": "synthetic review note"},
                "does_not_claim": "run_blocking",
            }
        )

        summary = build_prepared_run_partial_target_acknowledgement_summary(source)

        self.assertEqual(summary["classification"], "manual_pre_run_review_still_needs_review")
        self.assertEqual(
            [finding["code"] for finding in summary["remaining_review_findings"]],
            ["manual_parameter_context_note"],
        )

    def test_blocked_review_chain_cannot_become_acknowledged_ready(self) -> None:
        source = _load_input()
        source["review_chain_summary"]["classification"] = "parameter_review_chain_blocked"
        source["review_chain_summary"]["review_findings"].append(
            copy.deepcopy(source["review_chain_summary"]["review_findings"][0])
        )

        with self.assertRaisesRegex(ValueError, "exactly one partial target finding"):
            build_prepared_run_partial_target_acknowledgement_summary(source)

        source = _load_input()
        source["review_chain_summary"]["classification"] = "parameter_review_chain_blocked"
        summary = build_prepared_run_partial_target_acknowledgement_summary(source)

        self.assertEqual(
            summary["classification"],
            "partial_target_coverage_acknowledgement_blocked",
        )


if __name__ == "__main__":
    unittest.main()
