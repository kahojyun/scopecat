from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.prepared_run_review_gate import (
    build_prepared_run_review_gate_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prepared_run_review_gate" / "basic_gate"
ENVIRONMENT_OPERATION_FIXTURE = (
    ROOT / "tests" / "fixtures" / "environment_operation_review_bundle" / "basic_operation_review"
)


def _load_input() -> dict:
    return json.loads((FIXTURE / "review-gate-input.json").read_text(encoding="utf-8"))


def _expected_candidate() -> dict:
    return json.loads((FIXTURE / "expected-review-gate-summary.json").read_text(encoding="utf-8"))[
        "candidate_summary"
    ]


def _operation_summary_for_gate() -> dict:
    summary = json.loads(
        (
            ENVIRONMENT_OPERATION_FIXTURE / "expected-environment-operation-review-summary.json"
        ).read_text(encoding="utf-8")
    )["candidate_summary"]
    summary["operation_review_request"]["prepared_run_context_id"] = (
        "prepared-run-context-chevron-qA-required-context-case"
    )
    return summary


def _clear_non_parameter_findings(source: dict) -> None:
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    source["prepared_run_context_summary"]["workspace_context_findings"] = []
    source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
    source["scope_alignment_summary"]["review_findings"] = []
    source["environment_review_summary"]["environment_review_findings"] = []


class PreparedRunReviewGateSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_summary(self) -> None:
        summary = build_prepared_run_review_gate_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_prepared_run_review_gate_summary(source)

        source["prepared_run_context_summary"]["prepared_run_contexts"][0]["label"] = "mutated"
        source["prepared_run_context_summary"]["workspace_context_findings"][0]["basis"][
            "changed_observed"
        ] = 99

        self.assertEqual(summary["prepared_run_context"]["label"], "qA chevron manual run context")
        self.assertEqual(
            summary["aggregated_review_findings"][1]["basis"]["changed_observed"],
            1,
        )

    def test_policy_must_match_expected_boundary(self) -> None:
        source = _load_input()
        source["review_gate_policy"]["automatic_run_start"] = "performed"

        with self.assertRaisesRegex(ValueError, "automatic_run_start"):
            build_prepared_run_review_gate_summary(source)

    def test_child_summary_must_not_claim_execution(self) -> None:
        source = _load_input()
        source["environment_review_summary"]["environment_review_bundle_policy"][
            "code_import_execution"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "code_import_execution"):
            build_prepared_run_review_gate_summary(source)

    def test_needs_review_without_required_context_block(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["missing_context_findings"] = []

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_scope_review",
            {item["state"] for item in summary["review_items"]},
        )

    def test_prepared_context_findings_are_filtered_to_requested_context(self) -> None:
        source = _load_input()
        source["prepared_run_context_summary"]["missing_context_findings"][0][
            "prepared_run_context_id"
        ] = "prepared-run-context-other"
        source["prepared_run_context_summary"]["workspace_context_findings"][0][
            "prepared_run_context_id"
        ] = "prepared-run-context-other"
        source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
        source["scope_alignment_summary"]["review_findings"] = []
        source["environment_review_summary"]["environment_review_findings"] = []

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "ready_for_manual_review")
        self.assertEqual(summary["aggregated_review_findings"], [])
        self.assertEqual(
            {item["state"] for item in summary["review_items"]},
            {"ready_for_manual_review"},
        )

    def test_ready_when_all_review_areas_are_clear(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "ready_for_manual_review")
        self.assertEqual(summary["aggregated_review_findings"], [])
        self.assertEqual(
            {item["state"] for item in summary["review_items"]},
            {"ready_for_manual_review"},
        )

    def test_parameter_gate_needs_review_is_carried(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)
        source["parameter_state_gate_summary"]["gate_decision"]["gate_state"] = (
            "needs_parameter_review"
        )
        source["parameter_state_gate_summary"]["gate_decision"]["reason_codes"] = [
            "insufficient_trusted_entries"
        ]
        source["parameter_state_gate_summary"]["review_findings"] = [
            {
                "code": "insufficient_trusted_entries",
                "severity": "review",
                "basis": {"required_min_trusted_entries": 3, "trusted_entry_count": 2},
                "does_not_claim": "automatic_parameter_completion_or_write_back",
            }
        ]

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_parameter_review",
            {item["state"] for item in summary["review_items"]},
        )
        self.assertIn(
            "insufficient_trusted_entries",
            {finding["code"] for finding in summary["aggregated_review_findings"]},
        )

    def test_request_must_match_child_prepared_context_ids(self) -> None:
        source = _load_input()
        source["scope_alignment_summary"]["scope_summary"]["prepared_run_context_id"] = (
            "different-context"
        )

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_review_gate_summary(source)

    def test_optional_environment_operation_review_can_be_ready_evidence(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)
        source["environment_operation_review_summary"] = _operation_summary_for_gate()

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "ready_for_manual_review")
        self.assertIn(
            {
                "area": "environment_operation",
                "state": "ready_for_manual_review",
                "reason_codes": [],
                "finding_count": 0,
            },
            summary["review_items"],
        )
        self.assertEqual(summary["gate_decision"]["environment_operation"], "not_performed")

    def test_optional_environment_operation_findings_are_carried(self) -> None:
        source = _load_input()
        _clear_non_parameter_findings(source)
        operation_summary = _operation_summary_for_gate()
        operation_summary["operation_review_status"] = "operation_review_has_findings"
        operation_summary["operation_review_findings"] = [
            {
                "code": "uv_sync_result_has_findings",
                "severity": "review",
                "basis": "Prior uv sync result summary carries review findings.",
                "source": "uv_sync_result",
                "does_not_claim": "verified_synchronized_environment",
            }
        ]
        source["environment_operation_review_summary"] = operation_summary

        summary = build_prepared_run_review_gate_summary(source)

        self.assertEqual(summary["gate_decision"]["overall_state"], "manual_pre_run_review_needed")
        self.assertIn(
            "needs_environment_operation_review",
            {item["state"] for item in summary["review_items"]},
        )
        self.assertIn(
            "uv_sync_result_has_findings",
            {finding["code"] for finding in summary["aggregated_review_findings"]},
        )

    def test_optional_environment_operation_review_must_match_request_context(self) -> None:
        source = _load_input()
        source["environment_operation_review_summary"] = _operation_summary_for_gate()
        source["environment_operation_review_summary"]["operation_review_request"][
            "prepared_run_context_id"
        ] = "different-context"

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_review_gate_summary(source)

    def test_optional_environment_operation_review_keeps_review_summary_posture(self) -> None:
        source = _load_input()
        source["environment_operation_review_summary"] = _operation_summary_for_gate()
        source["environment_operation_review_summary"]["environment_operation_review_policy"][
            "summary_policy"
        ] = "export/package"

        with self.assertRaisesRegex(ValueError, "summary_policy"):
            build_prepared_run_review_gate_summary(source)


if __name__ == "__main__":
    unittest.main()
