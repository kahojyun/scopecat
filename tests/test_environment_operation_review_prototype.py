from __future__ import annotations

import copy
import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import (
    CommandRunResult,
    UvSyncIntent,
    UvSyncResult,
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
            summary["environment_operation_review_policy"]["run_blocking_decision"],
            "not_made",
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

    def test_review_surfaces_result_intent_and_command_mismatches(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        )
        intent_ref = copy.deepcopy(result.intent_ref)
        intent_ref["approval_id"] = "approval-other"
        command_result = copy.deepcopy(result.command_result)
        command_result["argv"] = ["uv", "sync", "--locked"]
        mismatched = replace(
            result,
            intent_ref=intent_ref,
            command_result=command_result,
        )

        review = review_uv_sync_operation(intent, mismatched)
        summary = review.to_dict()

        self.assertEqual(summary["operation_review_status"], "operation_review_has_findings")
        self.assertEqual(
            [finding["code"] for finding in summary["operation_review_findings"]],
            ["sync_result_intent_ref_mismatch", "sync_result_command_mismatch"],
        )

    def test_result_summary_edge_projection_requires_expected_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "command_result"):
            UvSyncResult.from_summary(
                {
                    "uv_sync_result_policy": {},
                    "uv_sync_intent_ref": {},
                    "result_status": "uv_sync_completed_success",
                    "result_findings": [],
                },
            )

        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        result_summary = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        ).to_summary()
        result_summary["result_findings"] = ["not-a-finding"]
        with self.assertRaisesRegex(ValueError, "uv sync result finding"):
            UvSyncResult.from_summary(result_summary)

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

    def test_review_can_consume_result_rehydrated_from_summary_edge(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        summary = _result(
            intent,
            CommandRunResult(exit_code=0, stdout="ok", stderr=""),
        ).to_summary()

        review = review_uv_sync_operation(intent, UvSyncResult.from_summary(summary))

        self.assertEqual(
            review.to_dict()["operation_review_status"],
            "uv_sync_completed_success_with_review_limits",
        )


if __name__ == "__main__":
    unittest.main()
