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
PROTOTYPE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "environment_operation"
    / "environment_operation_execution"
)


def _load_tiny_uv_intent_summary() -> dict:
    return json.loads(
        (PROTOTYPE_FIXTURE / "uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )


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
            set(summary),
            {
                "operation_review_request",
                "sync_intent_ref",
                "sync_result_ref",
                "operation_review_status",
                "operation_review_findings",
            },
        )
        self.assertEqual(
            summary["operation_review_status"],
            "uv_sync_completed_success_reviewed",
        )
        self.assertEqual(summary["operation_review_findings"], [])

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

    def test_launch_failure_result_reviews_as_findings(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, FileNotFoundError("uv executable was not found"))

        review = review_uv_sync_operation(intent, result)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_launch_failed", "uv_sync_result_not_success"],
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

        self.assertEqual(result.intent_ref["approval_id"], intent.approval_id)
        self.assertEqual(result.command_result["argv"], list(intent.argv))

        leaked_command_result = result.command_result
        leaked_command_result["argv"].append("--leaked")

        self.assertEqual(result.command_result["argv"], list(intent.argv))

    def test_operation_review_projection_is_copy_safe(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))
        review = review_uv_sync_operation(intent, result)

        leaked_intent_ref = review.intent_ref
        leaked_intent_ref["approval_id"] = "changed"
        leaked_result_ref = review.result_ref
        leaked_result_ref["argv"].append("--changed")

        summary = review.to_dict()
        self.assertEqual(summary["sync_intent_ref"]["approval_id"], intent.approval_id)
        self.assertEqual(summary["sync_result_ref"]["argv"], list(intent.argv))

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
            )

    def test_typed_result_rejects_inconsistent_status(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(intent, CommandRunResult(exit_code=0, stdout="ok", stderr=""))

        with self.assertRaisesRegex(ValueError, "result_status"):
            UvSyncResult(
                intent_ref=result.intent_ref,
                command_result=result.command_result,
                result_status="unknown",
                findings=result.findings,
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
            )


if __name__ == "__main__":
    unittest.main()
