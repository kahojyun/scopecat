from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import CommandRunResult, UvSyncIntent, execute_uv_sync

ROOT = Path(__file__).resolve().parents[1]
INTENT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"
TINY_UV_WORKSPACE = (
    ROOT / "tests" / "fixtures" / "environment_operation_execution" / "tiny_uv_workspace"
)
MISSING_LOCK_WORKSPACE = (
    ROOT / "tests" / "fixtures" / "environment_operation_execution" / "missing_lock_workspace"
)
ENVIRONMENT_OPERATION_MODULE = ROOT / "scopecat" / "environment_operation"


def _load_intent_summary() -> dict:
    return json.loads(
        (INTENT_FIXTURE / "expected-uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )["candidate_summary"]


def _load_tiny_uv_intent_summary() -> dict:
    summary = _load_intent_summary()
    summary["sync_request"]["dependency_groups"] = []
    summary["command_intent"]["argv"] = ["uv", "sync", "--locked", "--no-default-groups"]
    summary["command_intent"]["dependency_group_selection"]["requested_groups"] = []
    summary["command_intent"]["dependency_group_selection"]["group_matches"] = []
    summary["command_intent"]["dependency_group_selection"]["command_dependency_groups"] = []
    return summary


class FakeRunner:
    def __init__(self, result: CommandRunResult | BaseException) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandRunResult:
        self.calls.append({"argv": argv, "cwd": cwd, "timeout_seconds": timeout_seconds})
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class EnvironmentOperationEngineeringPrototypeTest(unittest.TestCase):
    def test_executes_approved_uv_sync_intent_through_injected_runner(self) -> None:
        intent = UvSyncIntent.from_summary(_load_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            project = workspace_root / "project"
            project.mkdir()
            runner = FakeRunner(CommandRunResult(exit_code=0, stdout="Resolved ok\n", stderr=""))

            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-chevron-qA-001",
                timeout_seconds=17,
                runner=runner,
            )

        self.assertEqual(
            runner.calls,
            [{"argv": intent.argv, "cwd": project.resolve(), "timeout_seconds": 17}],
        )
        self.assertEqual(record.result_status, "uv_sync_completed_success")
        self.assertEqual(record.execution_state, "completed_success")
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(record.stdout_summary, "Resolved ok")
        self.assertEqual(record.findings, ())

        summary = record.to_dict()
        self.assertEqual(
            summary["execution_policy"]["readiness_claim"],
            "not_claimed",
        )
        self.assertEqual(
            summary["command_result"]["output_capture"]["raw_output"],
            "not_recorded",
        )

    def test_execution_record_projects_route_local_result_summary(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            runner = FakeRunner(CommandRunResult(exit_code=0, stdout="ok", stderr=""))

            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-projection-001",
                runner=runner,
            )

        summary = record.to_result_summary(intent)

        self.assertEqual(
            summary["uv_sync_result_policy"]["result_authority"],
            "scopecat_uv_sync_execution_result",
        )
        self.assertEqual(
            summary["uv_sync_result_policy"]["dependency_sync"],
            "manager_result_not_verified_by_scopecat",
        )
        self.assertEqual(
            summary["uv_sync_intent_ref"]["command_intent"]["argv"],
            ["uv", "sync", "--locked", "--no-default-groups"],
        )
        self.assertEqual(summary["command_result"]["result_id"], "uv-sync-result-projection-001")
        self.assertEqual(summary["command_result"]["execution_state"], "completed_success")
        self.assertEqual(summary["result_status"], "uv_sync_completed_success")
        self.assertEqual(summary["result_findings"], [])
        self.assertEqual(
            {item["code"] for item in summary["attention"]},
            {
                "uv_sync_executed_by_scopecat",
                "bounded_output_summary_only",
                "runnable_readiness_not_claimed",
            },
        )

    def test_result_summary_rejects_mismatched_intent_projection(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                runner=FakeRunner(CommandRunResult(exit_code=0, stdout="", stderr="")),
            )

        mismatched = replace(intent, approval_id="approval-other")

        with self.assertRaisesRegex(ValueError, "approval_id"):
            record.to_result_summary(mismatched)

    def test_executes_real_uv_sync_against_tiny_workspace_fixture(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            shutil.copytree(TINY_UV_WORKSPACE, workspace_root)

            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-tiny-real-001",
                timeout_seconds=60,
            )

        self.assertEqual(record.result_status, "uv_sync_completed_success")
        self.assertEqual(record.execution_state, "completed_success")
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(record.findings, ())
        self.assertFalse(record.stdout_truncated)
        self.assertFalse(record.stderr_truncated)

    def test_failed_uv_process_is_review_finding_not_readiness_claim(self) -> None:
        intent = UvSyncIntent.from_summary(_load_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            runner = FakeRunner(
                CommandRunResult(
                    exit_code=1,
                    stdout="",
                    stderr="lockfile needs update",
                )
            )

            record = execute_uv_sync(intent, workspace_root=workspace_root, runner=runner)

        self.assertEqual(record.result_status, "uv_sync_completed_failed")
        self.assertEqual(record.execution_state, "completed_failed")
        self.assertEqual(record.exit_code, 1)
        self.assertEqual(record.stderr_summary, "lockfile needs update")
        self.assertEqual([finding.code for finding in record.findings], ["uv_sync_process_failed"])
        self.assertEqual(record.findings[0].does_not_claim, "synchronized_or_installed_environment")

        summary = record.to_result_summary(intent)
        self.assertEqual(summary["result_status"], "uv_sync_completed_failed")
        self.assertEqual(
            [finding["code"] for finding in summary["result_findings"]],
            ["uv_sync_process_failed"],
        )

    def test_real_locked_uv_failure_is_review_finding_not_runtime_truth(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            shutil.copytree(MISSING_LOCK_WORKSPACE, workspace_root)

            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-missing-lock-real-001",
                timeout_seconds=60,
            )

        self.assertEqual(record.result_status, "uv_sync_completed_failed")
        self.assertEqual(record.execution_state, "completed_failed")
        self.assertNotEqual(record.exit_code, 0)
        self.assertIn("lockfile", record.stderr_summary)
        self.assertEqual([finding.code for finding in record.findings], ["uv_sync_process_failed"])
        self.assertEqual(record.findings[0].does_not_claim, "synchronized_or_installed_environment")

    def test_timeout_is_recorded_without_claiming_sync(self) -> None:
        intent = UvSyncIntent.from_summary(_load_intent_summary())
        timeout = subprocess.TimeoutExpired(
            cmd=list(intent.argv),
            timeout=1,
            output="partial output",
            stderr=b"partial stderr",
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            runner = FakeRunner(timeout)

            record = execute_uv_sync(
                intent,
                workspace_root=workspace_root,
                timeout_seconds=1,
                runner=runner,
            )

        self.assertEqual(record.result_status, "uv_sync_timed_out")
        self.assertEqual(record.execution_state, "timed_out")
        self.assertIsNone(record.exit_code)
        self.assertEqual(record.stdout_summary, "partial output")
        self.assertEqual(record.stderr_summary, "partial stderr")
        self.assertEqual(
            [finding.code for finding in record.findings], ["uv_sync_process_timed_out"]
        )

    def test_launch_failure_is_recorded_without_claiming_manager_availability(self) -> None:
        intent = UvSyncIntent.from_summary(_load_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            runner = FakeRunner(FileNotFoundError("uv executable was not found"))

            record = execute_uv_sync(intent, workspace_root=workspace_root, runner=runner)

        self.assertEqual(record.result_status, "uv_sync_launch_failed")
        self.assertEqual(record.execution_state, "launch_failed")
        self.assertIsNone(record.exit_code)
        self.assertIn("uv executable was not found", record.stderr_summary)
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["uv_sync_process_launch_failed"],
        )
        self.assertEqual(
            record.findings[0].does_not_claim,
            "manager_available_or_environment_synchronized",
        )

    def test_intent_rejects_unapproved_or_unbounded_command_shapes(self) -> None:
        source = _load_intent_summary()
        source["sync_request"]["approved_operation"] = "inspect_environment"
        with self.assertRaisesRegex(ValueError, "approve uv_sync_intent"):
            UvSyncIntent.from_summary(source)

        source = _load_intent_summary()
        source["command_intent"]["argv"] = ["uv", "pip", "install", "unsafe"]
        with self.assertRaisesRegex(ValueError, "bounded uv sync argv"):
            UvSyncIntent.from_summary(source)

        source = _load_intent_summary()
        source["command_intent"]["environment_variables"] = ["UV_INDEX_URL=private"]
        with self.assertRaisesRegex(ValueError, "environment overrides"):
            UvSyncIntent.from_summary(source)

    def test_execution_cwd_must_stay_inside_existing_workspace_root(self) -> None:
        source = _load_intent_summary()
        source["sync_request"]["working_directory"] = "../outside"
        source["command_intent"]["working_directory"] = "../outside"
        with self.assertRaisesRegex(ValueError, "relative workspace path"):
            UvSyncIntent.from_summary(source)

        intent = UvSyncIntent.from_summary(_load_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "working_directory must exist"):
                execute_uv_sync(
                    intent,
                    workspace_root=workspace_root,
                    runner=FakeRunner(CommandRunResult(exit_code=0, stdout="", stderr="")),
                )

    def test_environment_operation_prototype_does_not_import_implementation_candidates(
        self,
    ) -> None:
        offenders = []
        for path in ENVIRONMENT_OPERATION_MODULE.glob("*.py"):
            if "implementation_candidates" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
