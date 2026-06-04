from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import (
    CommandRunResult,
    UvSyncIntent,
    run_uv_sync_operation,
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
    summary = json.loads(
        (PROTOTYPE_FIXTURE / "uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )
    summary["command_intent"]["argv"] = ["uv", "sync", "--locked", "--no-default-groups"]
    return summary


def _runtime_facts() -> dict[str, object]:
    return {
        "python_version": "3.12.8",
        "python_implementation": "CPython",
        "executable": "/workspace/project/.venv/bin/python",
        "prefix": "/workspace/project/.venv",
        "base_prefix": "/opt/python/3.12",
        "is_virtual_environment": True,
    }


class QueueRunner:
    def __init__(self, *results: CommandRunResult) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandRunResult:
        self.calls.append({"argv": argv, "cwd": cwd, "timeout_seconds": timeout_seconds})
        if not self.results:
            raise AssertionError("runner called more times than expected")
        return self.results.pop(0)


class EnvironmentOperationWorkflowTest(unittest.TestCase):
    def test_successful_sync_operation_runs_review_and_runtime_probe(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        runner = QueueRunner(
            CommandRunResult(exit_code=0, stdout="sync ok", stderr=""),
            CommandRunResult(exit_code=0, stdout=json.dumps(_runtime_facts()), stderr=""),
        )

        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            project = workspace_root / "project"
            project.mkdir()

            run = run_uv_sync_operation(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-workflow-001",
                review_id="uv-sync-result-workflow-001.review",
                probe_result_id="uv-runtime-probe-result-workflow-001",
                timeout_seconds=13,
                runtime_probe_timeout_seconds=7,
                runner=runner,
            )

        self.assertEqual(run.sync_result.result_status, "uv_sync_completed_success")
        self.assertEqual(
            run.operation_review.review_status,
            "uv_sync_completed_success_with_review_limits",
        )
        self.assertEqual(run.runtime_probe_state, "performed")
        self.assertIsNotNone(run.runtime_probe_intent)
        self.assertIsNotNone(run.runtime_probe_execution_record)
        self.assertIsNotNone(run.runtime_probe_result)
        self.assertEqual(
            run.runtime_probe_result.result_status, "uv_runtime_probe_completed_success"
        )
        self.assertEqual(
            runner.calls,
            [
                {"argv": intent.argv, "cwd": project.resolve(), "timeout_seconds": 13},
                {
                    "argv": run.runtime_probe_intent.argv,
                    "cwd": project.resolve(),
                    "timeout_seconds": 7,
                },
            ],
        )

        summary = run.to_summary()
        self.assertEqual(
            summary["environment_operation_run_policy"]["summary_policy"],
            "review_summary",
        )
        self.assertEqual(
            summary["environment_operation_run_policy"]["readiness_claim"],
            "not_claimed",
        )
        self.assertEqual(summary["runtime_probe"]["runtime_probe_state"], "performed")
        self.assertEqual(
            summary["runtime_probe"]["runtime_probe_result"]["runtime_facts"][
                "is_virtual_environment"
            ],
            True,
        )

    def test_failed_sync_operation_skips_runtime_probe(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        runner = QueueRunner(
            CommandRunResult(exit_code=1, stdout="", stderr="lockfile needs update")
        )

        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            run = run_uv_sync_operation(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-workflow-failed-001",
                runner=runner,
            )

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(run.sync_result.result_status, "uv_sync_completed_failed")
        self.assertEqual(run.runtime_probe_state, "not_eligible_sync_not_successful")
        self.assertIsNone(run.runtime_probe_intent)
        self.assertIsNone(run.runtime_probe_execution_record)
        self.assertIsNone(run.runtime_probe_result)
        self.assertIn(
            "uv_sync_result_not_success",
            [finding.code for finding in run.operation_review.findings],
        )

        summary = run.to_summary()
        self.assertEqual(
            summary["runtime_probe"]["runtime_probe_state"],
            "not_eligible_sync_not_successful",
        )
        self.assertIsNone(summary["runtime_probe"]["runtime_probe_result"])

    def test_runtime_probe_can_be_explicitly_skipped_after_successful_sync(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        runner = QueueRunner(CommandRunResult(exit_code=0, stdout="sync ok", stderr=""))

        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            run = run_uv_sync_operation(
                intent,
                workspace_root=workspace_root,
                run_runtime_probe=False,
                runner=runner,
            )

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(run.sync_result.result_status, "uv_sync_completed_success")
        self.assertEqual(run.runtime_probe_state, "not_requested")
        self.assertIsNone(run.runtime_probe_result)


if __name__ == "__main__":
    unittest.main()
