from __future__ import annotations

import json
import unittest
from pathlib import Path

from scopecat.environment_operation import (
    UvSyncExecutionRecord,
    UvSyncFinding,
    UvSyncIntent,
    UvSyncResult,
    review_uv_sync_operation,
)
from scopecat.prepared_run import (
    PreparedRunReviewGateRequest,
    build_prepared_run_review_gate_summary,
    build_prepared_run_review_view_state,
    compose_prepared_run_review_gate,
    project_environment_operation_review_for_prepared_run,
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


def _typed_operation_review_for_gate(*, execution_state: str = "completed_failed"):
    intent = UvSyncIntent(
        request_id="uv-sync-request-chevron-qA-0001",
        approval_id="uv-sync-approval-chevron-qA-0001",
        working_directory="project",
        argv=("uv", "sync", "--locked", "--no-default-groups"),
    )
    if execution_state == "completed_success":
        exit_code = 0
        stderr_summary = ""
        findings = ()
    else:
        exit_code = 1
        stderr_summary = "synthetic uv failure"
        findings = (
            UvSyncFinding(
                code="uv_sync_process_failed",
                severity="review",
                basis="The Scopecat-run uv sync process exited with a non-zero status.",
                does_not_claim="synchronized_or_installed_environment",
            ),
        )
    record = UvSyncExecutionRecord(
        result_id="uv-sync-result-chevron-qA-0001",
        intent_request_id=intent.request_id,
        approval_id=intent.approval_id,
        working_directory=intent.working_directory,
        local_execution_cwd="synthetic-workspace/project",
        argv=intent.argv,
        execution_state=execution_state,
        exit_code=exit_code,
        started_at="2026-06-01T00:00:00.000Z",
        completed_at="2026-06-01T00:00:00.010Z",
        duration_ms=10,
        stdout_summary="",
        stderr_summary=stderr_summary,
        stdout_truncated=False,
        stderr_truncated=False,
        findings=findings,
    )
    result = UvSyncResult.from_execution(intent, record)
    return review_uv_sync_operation(
        intent,
        result,
        review_id="operation-review-chevron-qA-typed-001",
    )


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

    def test_typed_environment_operation_review_evidence_flows_to_gate_and_view_state(
        self,
    ) -> None:
        source = _load_input()
        _clear_review_findings(source)
        source["environment_operation_review_summary"] = (
            project_environment_operation_review_for_prepared_run(
                _typed_operation_review_for_gate(),
                prepared_run_context_id=source["review_gate_request"]["prepared_run_context_id"],
            )
        )

        gate_summary = build_prepared_run_review_gate_summary(source)
        view_state = build_prepared_run_review_view_state(
            {
                "view_state_request": {"view_state_id": "typed-operation-review-view-001"},
                "review_gate_summary": gate_summary,
            }
        )

        self.assertEqual(
            gate_summary["gate_decision"]["overall_state"],
            "manual_pre_run_review_needed",
        )
        self.assertIn(
            {
                "area": "environment_operation",
                "state": "needs_environment_operation_review",
                "reason_codes": [
                    "uv_sync_process_failed",
                    "uv_sync_result_not_success",
                ],
                "finding_count": 2,
            },
            gate_summary["review_items"],
        )
        self.assertEqual(
            [
                finding["code"]
                for finding in gate_summary["aggregated_review_findings"]
                if finding["source_area"] == "environment_operation"
            ],
            ["uv_sync_process_failed", "uv_sync_result_not_success"],
        )
        self.assertIn(
            "review-item-05-environment_operation",
            {row["row_id"] for row in view_state["review_item_rows"]},
        )
        self.assertEqual(gate_summary["gate_decision"]["environment_operation"], "not_performed")
        self.assertEqual(view_state["header"]["environment_operation"], "not_performed")
        self.assertEqual(view_state["view_state_policy"]["dependency_sync"], "not_performed")

    def test_successful_typed_environment_operation_review_is_ready_prior_evidence(
        self,
    ) -> None:
        source = _load_input()
        _clear_review_findings(source)
        source["environment_operation_review_summary"] = (
            project_environment_operation_review_for_prepared_run(
                _typed_operation_review_for_gate(execution_state="completed_success"),
                prepared_run_context_id=source["review_gate_request"]["prepared_run_context_id"],
            )
        )

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
        self.assertEqual(
            [
                finding
                for finding in summary["aggregated_review_findings"]
                if finding["source_area"] == "environment_operation"
            ],
            [],
        )

    def test_optional_environment_operation_review_keeps_local_review_posture(self) -> None:
        source = _load_input()
        source["environment_operation_review_summary"] = _operation_summary_for_gate()
        source["environment_operation_review_summary"]["environment_operation_review_policy"][
            "summary_policy"
        ] = "export/package"

        with self.assertRaisesRegex(ValueError, "summary_policy"):
            build_prepared_run_review_gate_summary(source)

    def test_discovery_environment_operation_review_keeps_external_status_language(self) -> None:
        source = _load_input()
        source["environment_operation_review_summary"] = _operation_summary_for_gate()
        source["environment_operation_review_summary"]["operation_review_status"] = (
            "uv_sync_completed_success_with_review_limits"
        )

        with self.assertRaisesRegex(ValueError, "unsupported environment operation review status"):
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
