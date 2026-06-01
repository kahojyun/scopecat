from __future__ import annotations

import json
import unittest
from pathlib import Path

from scopecat.prepared_run import (
    PreparedRunReviewGateRequest,
    build_prepared_run_review_gate_summary,
    compose_prepared_run_review_gate,
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


def _clear_review_findings(source: dict) -> None:
    source["prepared_run_context_summary"]["missing_context_findings"] = []
    source["prepared_run_context_summary"]["workspace_context_findings"] = []
    source["scope_alignment_summary"]["classification"] = "scope_alignment_ready"
    source["scope_alignment_summary"]["review_findings"] = []
    source["environment_review_summary"]["environment_review_findings"] = []


class PreparedRunReviewGatePrototypeTest(unittest.TestCase):
    def test_raw_adapter_matches_validated_candidate_output(self) -> None:
        summary = build_prepared_run_review_gate_summary(_load_input())

        self.assertEqual(summary, _expected_candidate())

    def test_typed_request_result_round_trip_matches_raw_adapter(self) -> None:
        source = _load_input()
        request = PreparedRunReviewGateRequest.from_dict(source)
        result = compose_prepared_run_review_gate(request)

        self.assertEqual(
            request.prepared_run_context_id,
            source["review_gate_request"]["prepared_run_context_id"],
        )
        self.assertEqual(request.measurement_id, source["review_gate_request"]["measurement_id"])
        self.assertEqual(result.to_dict(), build_prepared_run_review_gate_summary(source))

    def test_request_and_result_do_not_alias_input_or_output_dicts(self) -> None:
        source = _load_input()
        request = PreparedRunReviewGateRequest.from_dict(source)
        result = compose_prepared_run_review_gate(request)
        summary = result.to_dict()

        source["prepared_run_context_summary"]["prepared_run_contexts"][0]["label"] = "mutated"
        summary["prepared_run_context"]["label"] = "mutated again"
        summary["aggregated_review_findings"][1]["basis"]["changed_observed"] = 99

        self.assertEqual(
            request.source["prepared_run_context_summary"]["prepared_run_contexts"][0]["label"],
            "qA chevron manual run context",
        )
        self.assertEqual(result.prepared_run_context["label"], "qA chevron manual run context")
        self.assertEqual(
            result.to_dict()["aggregated_review_findings"][1]["basis"]["changed_observed"],
            1,
        )

    def test_promoted_gate_preserves_manual_review_non_claims(self) -> None:
        summary = build_prepared_run_review_gate_summary(_load_input())

        self.assertEqual(summary["gate_decision"]["run_start_claim"], "not_claimed")
        self.assertEqual(summary["gate_decision"]["hardware_control"], "not_performed")
        self.assertEqual(summary["gate_decision"]["parameter_write_back"], "not_performed")
        self.assertEqual(summary["gate_decision"]["environment_operation"], "not_performed")
        self.assertEqual(summary["gate_decision"]["code_import_execution"], "not_performed")
        self.assertEqual(summary["review_gate_policy"]["dependency_sync"], "not_performed")
        self.assertEqual(summary["review_gate_policy"]["shared_gate_schema"], "not_defined")

    def test_optional_environment_operation_review_evidence_is_aggregated(self) -> None:
        source = _load_input()
        _clear_review_findings(source)
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
            {
                "area": "environment_operation",
                "state": "needs_environment_operation_review",
                "reason_codes": ["uv_sync_result_has_findings"],
                "finding_count": 1,
            },
            summary["review_items"],
        )
        self.assertIn(
            "uv_sync_result_has_findings",
            {finding["code"] for finding in summary["aggregated_review_findings"]},
        )
        self.assertEqual(summary["gate_decision"]["environment_operation"], "not_performed")

    def test_optional_environment_operation_review_keeps_local_review_posture(self) -> None:
        source = _load_input()
        source["environment_operation_review_summary"] = _operation_summary_for_gate()
        source["environment_operation_review_summary"]["environment_operation_review_policy"][
            "summary_policy"
        ] = "export/package"

        with self.assertRaisesRegex(ValueError, "summary_policy"):
            build_prepared_run_review_gate_summary(source)

    def test_child_summaries_must_keep_non_execution_boundary(self) -> None:
        source = _load_input()
        source["parameter_state_gate_summary"]["gate_decision"]["run_start_claim"] = "claimed"

        with self.assertRaisesRegex(ValueError, "run start"):
            build_prepared_run_review_gate_summary(source)

    def test_child_summaries_must_match_requested_prepared_run_context(self) -> None:
        source = _load_input()
        source["scope_alignment_summary"]["scope_summary"]["prepared_run_context_id"] = (
            "different-context"
        )

        with self.assertRaisesRegex(ValueError, "prepared_run_context_id"):
            build_prepared_run_review_gate_summary(source)


if __name__ == "__main__":
    unittest.main()
