from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import (
    CommandRunResult,
    UvSyncIntent,
    UvSyncResult,
    execute_uv_sync,
    review_uv_sync_operation,
)

ROOT = Path(__file__).resolve().parents[3]
INTENT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"


def _load_tiny_uv_intent_summary() -> dict:
    summary = json.loads(
        (INTENT_FIXTURE / "expected-uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]
    summary["sync_request"]["dependency_groups"] = []
    summary["command_intent"]["argv"] = ["uv", "sync", "--locked", "--no-default-groups"]
    summary["command_intent"]["dependency_group_selection"]["requested_groups"] = []
    summary["command_intent"]["dependency_group_selection"]["group_matches"] = []
    summary["command_intent"]["dependency_group_selection"]["command_dependency_groups"] = []
    return summary


class FakeRunner:
    def __init__(self, result: CommandRunResult | BaseException) -> None:
        self.result = result

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandRunResult:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _result(
    intent: UvSyncIntent,
    result: CommandRunResult | BaseException,
) -> UvSyncResult:
    with TemporaryDirectory() as tmp:
        workspace_root = Path(tmp)
        (workspace_root / "project").mkdir()
        record = execute_uv_sync(
            intent,
            workspace_root=workspace_root,
            runner=FakeRunner(result),
        )
    return UvSyncResult.from_execution(intent, record)


def _finding_non_claims(summary: dict) -> dict[str, str]:
    return {
        finding["code"]: finding["does_not_claim"]
        for finding in summary["operation_review_findings"]
    }


class EnvironmentOperationReviewPrototypeTest(unittest.TestCase):
    def test_successful_uv_sync_result_reviews_with_limits(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )

        review = review_uv_sync_operation(
            intent,
            result,
            review_id="operation-review-success-001",
        )
        summary = review.to_dict()

        self.assertEqual(
            summary["operation_review_status"],
            "uv_sync_completed_success_with_review_limits",
        )
        self.assertEqual(summary["operation_review_findings"], [])
        self.assertEqual(
            summary["environment_operation_review_policy"]["readiness_claim"],
            "not_claimed",
        )
        self.assertEqual(
            {item["code"] for item in summary["attention"]},
            {
                "operation_review_only",
                "package_state_not_verified",
                "code_execution_not_granted",
            },
        )

    def test_failed_uv_sync_result_is_review_finding_not_run_block(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            CommandRunResult(exit_code=1, stdout="", stderr="uv failed"),
        )

        review = review_uv_sync_operation(intent, result)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_failed", "uv_sync_result_not_success"],
        )
        self.assertEqual(
            _finding_non_claims(summary),
            {
                "uv_sync_process_failed": "synchronized_or_installed_environment",
                "uv_sync_result_not_success": "synchronized_or_installed_environment",
            },
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["run_blocking_decision"],
            "not_made",
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["readiness_claim"],
            "not_claimed",
        )

    def test_timeout_result_reviews_as_non_success(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            subprocess.TimeoutExpired(
                cmd=list(intent.argv),
                timeout=1,
                output="partial",
                stderr="timed out",
            ),
        )

        review = review_uv_sync_operation(intent, result)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_timed_out", "uv_sync_result_not_success"],
        )
        self.assertEqual(
            _finding_non_claims(summary),
            {
                "uv_sync_process_timed_out": "synchronized_or_installed_environment",
                "uv_sync_result_not_success": "synchronized_or_installed_environment",
            },
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["readiness_claim"],
            "not_claimed",
        )

    def test_launch_failure_result_reviews_without_manager_availability_claim(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, FileNotFoundError("uv executable was not found"))

        review = review_uv_sync_operation(intent, result)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_launch_failed", "uv_sync_result_not_success"],
        )
        self.assertEqual(
            _finding_non_claims(summary),
            {
                "uv_sync_process_launch_failed": ("manager_available_or_environment_synchronized"),
                "uv_sync_result_not_success": "synchronized_or_installed_environment",
            },
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["run_blocking_decision"],
            "not_made",
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["readiness_claim"],
            "not_claimed",
        )

    def test_review_surfaces_result_intent_and_command_mismatches(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )
        summary = result.to_summary()
        summary["uv_sync_intent_ref"]["approval_id"] = "approval-other"
        summary["command_result"]["argv"] = [
            "uv",
            "sync",
            "--locked",
            "--no-default-groups",
            "--group",
            "extra",
        ]

        mismatched = UvSyncResult(
            intent_ref=summary["uv_sync_intent_ref"],
            command_result=summary["command_result"],
            result_status=result.result_status,
            findings=result.findings,
            attention=result.attention,
        )

        review = review_uv_sync_operation(intent, mismatched)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["sync_result_intent_ref_mismatch", "sync_result_command_mismatch"],
        )

    def test_review_surfaces_result_identifier_mismatch(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )
        summary = result.to_summary()
        summary["command_result"]["intent_request_id"] = "request-other"
        mismatched = UvSyncResult(
            intent_ref=summary["uv_sync_intent_ref"],
            command_result=summary["command_result"],
            result_status=result.result_status,
            findings=result.findings,
            attention=result.attention,
        )

        review = review_uv_sync_operation(intent, mismatched)

        self.assertEqual(
            [finding.code for finding in review.findings],
            ["sync_result_intent_mismatch"],
        )

    def test_result_summary_projection_is_copy_safe(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))

        summary = result.to_summary()
        summary["uv_sync_intent_ref"]["approval_id"] = "changed"
        summary["command_result"]["argv"].append("--changed")
        summary["attention"][0]["code"] = "changed"

        self.assertEqual(result.intent_ref["approval_id"], intent.approval_id)
        self.assertEqual(result.command_result["argv"], list(intent.argv))
        self.assertEqual(result.attention[0]["code"], "uv_sync_executed_by_scopecat")

        leaked_command_result = result.command_result
        leaked_command_result["argv"].append("--leaked")
        leaked_attention = result.attention
        leaked_attention[0]["code"] = "leaked"

        self.assertEqual(result.command_result["argv"], list(intent.argv))
        self.assertEqual(result.attention[0]["code"], "uv_sync_executed_by_scopecat")

    def test_operation_review_projection_is_copy_safe(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))
        review = review_uv_sync_operation(intent, result)

        leaked_intent_ref = review.intent_ref
        leaked_intent_ref["approval_id"] = "changed"
        leaked_result_ref = review.result_ref
        leaked_result_ref["argv"].append("--changed")
        leaked_attention = review.attention
        leaked_attention[0]["code"] = "changed"

        summary = review.to_dict()
        self.assertEqual(summary["sync_intent_ref"]["approval_id"], intent.approval_id)
        self.assertEqual(summary["sync_result_ref"]["argv"], list(intent.argv))
        self.assertEqual(summary["attention"][0]["code"], "operation_review_only")

    def test_result_summary_projection_does_not_leak_extra_constructor_fields(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))
        intent_ref = result.intent_ref
        command_result = result.command_result
        intent_ref["extra_secret"] = "not exported"
        intent_ref["command_intent"]["extra_secret"] = "not exported"
        command_result["raw_stdout"] = "not exported"
        command_result["output_capture"]["raw_stdout"] = "not exported"

        projected = UvSyncResult(
            intent_ref=intent_ref,
            command_result=command_result,
            result_status=result.result_status,
            findings=result.findings,
            attention=result.attention,
        ).to_summary()

        self.assertNotIn("extra_secret", projected["uv_sync_intent_ref"])
        self.assertNotIn("extra_secret", projected["uv_sync_intent_ref"]["command_intent"])
        self.assertNotIn("raw_stdout", projected["command_result"])
        self.assertNotIn("raw_stdout", projected["command_result"]["output_capture"])

    def test_typed_result_rejects_raw_finding_objects(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))

        with self.assertRaisesRegex(ValueError, "UvSyncFinding"):
            UvSyncResult(
                intent_ref=result.intent_ref,
                command_result=result.command_result,
                result_status=result.result_status,
                findings=({"code": "raw-dict"},),  # type: ignore[arg-type]
                attention=result.attention,
            )

    def test_typed_result_rejects_inconsistent_status_and_malformed_attention(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))

        with self.assertRaisesRegex(ValueError, "result_status"):
            UvSyncResult(
                intent_ref=result.intent_ref,
                command_result=result.command_result,
                result_status="unknown",
                findings=result.findings,
                attention=result.attention,
            )

        command_result = result.command_result
        command_result["execution_state"] = "completed_failed"
        command_result["exit_code"] = 1
        with self.assertRaisesRegex(ValueError, "result_status"):
            UvSyncResult(
                intent_ref=result.intent_ref,
                command_result=command_result,
                result_status=result.result_status,
                findings=result.findings,
                attention=result.attention,
            )

        bad_attention = result.attention
        del bad_attention[0]["does_not_claim"]
        with self.assertRaisesRegex(ValueError, "does_not_claim"):
            UvSyncResult(
                intent_ref=result.intent_ref,
                command_result=result.command_result,
                result_status=result.result_status,
                findings=result.findings,
                attention=bad_attention,
            )


if __name__ == "__main__":
    unittest.main()
