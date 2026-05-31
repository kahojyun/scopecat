from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_parameter_state_gate import (
    build_prepared_run_parameter_state_gate_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_parameter_state_gate" / "basic_gate"


def _load_input() -> dict:
    return json.loads((FIXTURE / "gate-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-gate-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


class PreparedRunParameterStateGateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_parameter_state_gate_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_parameter_state_gate_summary(source)

        source["parameter_state_consumption_summary"]["prepared_run_context"]["label"] = "mutated"
        source["parameter_state_consumption_summary"]["trusted_entries"][0]["path"] = "mutated"

        self.assertEqual(
            summary["prepared_run_context"]["label"],
            "qA chevron manual run context from stored parameter state",
        )
        self.assertEqual(
            summary["parameter_state_gate_input"]["trusted_entry_paths"][0],
            "qubits.qA.drive_frequency_hz",
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["gate_policy"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_parameter_state_gate_summary(source)

    def test_consumption_summary_must_not_claim_writeback(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["consumption_policy"][
            "parameter_write_back"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "parameter_write_back"):
            build_prepared_run_parameter_state_gate_summary(source)

    def test_consumption_findings_make_gate_need_review(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["classification"] = (
            "prepared_run_parameter_state_needs_review"
        )
        source["parameter_state_consumption_summary"]["review_findings"] = [
            {
                "code": "parameter_state_read_view_not_ready",
                "severity": "review",
                "basis": "stored_parameter_state_observed_with_mismatch",
                "does_not_claim": "fresh_storage_read_or_automatic_repair",
            }
        ]

        summary = build_prepared_run_parameter_state_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["gate_state"], "needs_parameter_review")
        self.assertIn(
            "parameter_consumption_needs_review",
            summary["gate_decision"]["reason_codes"],
        )
        self.assertIn(
            "parameter_consumption_finding",
            {finding["code"] for finding in summary["review_findings"]},
        )

    def test_unavailable_consumption_blocks_required_parameter_context(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["classification"] = (
            "prepared_run_parameter_state_unavailable_for_review"
        )
        source["parameter_state_consumption_summary"]["parameter_state"] = None
        source["parameter_state_consumption_summary"]["trusted_entries"] = []

        summary = build_prepared_run_parameter_state_gate_summary(source)

        self.assertEqual(
            summary["gate_decision"]["gate_state"],
            "blocked_by_required_parameter_context",
        )
        self.assertIn(
            "required_parameter_context_unavailable",
            summary["gate_decision"]["reason_codes"],
        )

    def test_insufficient_trusted_entries_need_review(self) -> None:
        source = _load_input()
        source["gate_request"]["required_min_trusted_entries"] = 3

        summary = build_prepared_run_parameter_state_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["gate_state"], "needs_parameter_review")
        self.assertIn("insufficient_trusted_entries", summary["gate_decision"]["reason_codes"])

    def test_state_id_mismatch_needs_review(self) -> None:
        source = _load_input()
        source["parameter_state_consumption_summary"]["parameter_state"]["state_id"] = (
            "param-state-other"
        )

        summary = build_prepared_run_parameter_state_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["gate_state"], "needs_parameter_review")
        self.assertIn("gate_state_id_mismatch", summary["gate_decision"]["reason_codes"])

    def test_request_must_match_consumption_scope(self) -> None:
        source = _load_input()
        source["gate_request"]["prepared_run_context_id"] = "different-context"

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_parameter_state_gate_summary(source)


if __name__ == "__main__":
    unittest.main()
