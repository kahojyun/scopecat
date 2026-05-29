from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import (
    CommandRunResult,
    UvSyncIntent,
    execute_uv_sync,
    review_uv_sync_operation,
)

ROOT = Path(__file__).resolve().parents[1]
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


def _result_summary(
    intent: UvSyncIntent,
    result: CommandRunResult | BaseException,
) -> dict:
    with TemporaryDirectory() as tmp:
        workspace_root = Path(tmp)
        (workspace_root / "project").mkdir()
        record = execute_uv_sync(
            intent,
            workspace_root=workspace_root,
            runner=FakeRunner(result),
        )
    return record.to_result_summary(intent)


class EnvironmentOperationReviewPrototypeTest(unittest.TestCase):
    def test_successful_uv_sync_result_reviews_with_limits(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result_summary = _result_summary(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )

        review = review_uv_sync_operation(
            intent,
            result_summary,
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
        result_summary = _result_summary(
            intent,
            CommandRunResult(exit_code=1, stdout="", stderr="uv failed"),
        )

        review = review_uv_sync_operation(intent, result_summary)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_failed", "uv_sync_result_not_success"],
        )
        self.assertEqual(
            summary["environment_operation_review_policy"]["run_blocking_decision"],
            "not_made",
        )

    def test_timeout_result_reviews_as_non_success(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result_summary = _result_summary(
            intent,
            subprocess.TimeoutExpired(
                cmd=list(intent.argv),
                timeout=1,
                output="partial",
                stderr="timed out",
            ),
        )

        review = review_uv_sync_operation(intent, result_summary)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["uv_sync_process_timed_out", "uv_sync_result_not_success"],
        )

    def test_review_surfaces_result_intent_and_command_mismatches(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result_summary = _result_summary(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )
        mismatched = copy.deepcopy(result_summary)
        mismatched["uv_sync_intent_ref"]["approval_id"] = "approval-other"
        mismatched["command_result"]["argv"] = ["uv", "sync", "--locked"]

        review = review_uv_sync_operation(intent, mismatched)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["sync_result_intent_ref_mismatch", "sync_result_command_mismatch"],
        )

    def test_review_requires_result_summary_shape(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())

        with self.assertRaisesRegex(ValueError, "command_result"):
            review_uv_sync_operation(
                intent,
                {
                    "uv_sync_result_policy": {},
                    "uv_sync_intent_ref": {},
                    "result_status": "uv_sync_completed_success",
                    "result_findings": [],
                },
            )

        result_summary = _result_summary(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )
        result_summary["result_findings"] = ["not-a-finding"]
        with self.assertRaisesRegex(ValueError, "result finding"):
            review_uv_sync_operation(intent, result_summary)


if __name__ == "__main__":
    unittest.main()
