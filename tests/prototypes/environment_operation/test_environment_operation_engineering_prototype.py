from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scopecat.environment_operation import (
    CommandRunResult,
    SubprocessUvRunner,
    UvSyncIntent,
    UvSyncResult,
    execute_uv_sync,
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
TINY_UV_WORKSPACE = PROTOTYPE_FIXTURE / "tiny_uv_workspace"
MISSING_LOCK_WORKSPACE = PROTOTYPE_FIXTURE / "missing_lock_workspace"
ENVIRONMENT_OPERATION_MODULE = ROOT / "src" / "scopecat" / "environment_operation"


def _load_intent_summary() -> dict:
    return json.loads(
        (PROTOTYPE_FIXTURE / "uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )


def _load_tiny_uv_intent_summary() -> dict:
    return _load_intent_summary()


def _uv_executable() -> Path:
    resolved = shutil.which("uv")
    if resolved is None:
        raise unittest.SkipTest("uv executable not available")
    return Path(resolved)


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
                result_id="uv-sync-result-001",
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
        self.assertEqual(set(summary), {"command_result", "result_status", "findings"})
        self.assertEqual(
            summary["command_result"]["output_capture"]["raw_output"],
            "not_recorded",
        )

    def test_execution_record_projects_route_local_typed_result_summary(self) -> None:
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

        result = UvSyncResult.from_execution(intent, record)
        summary = result.to_summary()

        self.assertEqual(
            set(summary),
            {"uv_sync_intent_ref", "command_result", "result_status", "result_findings"},
        )
        self.assertEqual(
            set(summary["uv_sync_intent_ref"]["command_intent"]),
            {"manager", "operation", "working_directory", "argv"},
        )
        self.assertEqual(
            summary["uv_sync_intent_ref"]["command_intent"]["argv"],
            ["uv", "sync", "--locked", "--no-default-groups"],
        )
        self.assertEqual(summary["command_result"]["result_id"], "uv-sync-result-projection-001")
        self.assertEqual(summary["command_result"]["execution_state"], "completed_success")
        self.assertEqual(summary["result_status"], "uv_sync_completed_success")
        self.assertEqual(summary["result_findings"], [])
        self.assertEqual(record.to_result_summary(intent), summary)

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

    def test_root_level_working_directory_intent_can_execute(self) -> None:
        source = _load_tiny_uv_intent_summary()
        source["sync_request"]["working_directory"] = "."
        source["command_intent"]["working_directory"] = "."
        intent = UvSyncIntent.from_summary(source)
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            runner = FakeRunner(CommandRunResult(exit_code=0, stdout="", stderr=""))

            execute_uv_sync(intent, workspace_root=workspace_root, runner=runner)

        self.assertEqual(runner.calls[0]["cwd"], workspace_root.resolve())

    def test_subprocess_runner_uses_resolved_uv_and_empty_child_environment(self) -> None:
        runner = SubprocessUvRunner(uv_executable="/opt/scopecat-test/bin/uv")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with mock.patch.object(subprocess, "run", return_value=completed) as run:
            result = runner.run(
                ("uv", "sync", "--locked", "--no-default-groups"),
                cwd=Path("/tmp"),
                timeout_seconds=11,
            )

        self.assertEqual(result.exit_code, 0)
        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            ("/opt/scopecat-test/bin/uv", "sync", "--locked", "--no-default-groups"),
        )
        self.assertEqual(run.call_args.kwargs["env"], {})

    def test_default_subprocess_execution_requires_explicit_uv_executable(self) -> None:
        intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            with self.assertRaisesRegex(ValueError, "uv_executable"):
                execute_uv_sync(intent, workspace_root=workspace_root)

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
                uv_executable=_uv_executable(),
            )

        self.assertEqual(record.result_status, "uv_sync_completed_success")
        self.assertEqual(record.execution_state, "completed_success")
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(record.findings, ())
        self.assertFalse(record.stdout_truncated)
        self.assertFalse(record.stderr_truncated)

    def test_failed_uv_process_is_review_finding(self) -> None:
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
                uv_executable=_uv_executable(),
            )

        self.assertEqual(record.result_status, "uv_sync_completed_failed")
        self.assertEqual(record.execution_state, "completed_failed")
        self.assertNotEqual(record.exit_code, 0)
        self.assertFalse(record.stderr_truncated)
        self.assertEqual([finding.code for finding in record.findings], ["uv_sync_process_failed"])

    def test_timeout_is_recorded_as_review_finding(self) -> None:
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

    def test_launch_failure_is_recorded_as_review_finding(self) -> None:
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
        source["command_intent"]["argv"] = [
            "uv",
            "sync",
            "--locked",
            "--no-default-groups",
            "--group",
            "bad group",
        ]
        with self.assertRaisesRegex(ValueError, "group"):
            UvSyncIntent.from_summary(source)

        source = _load_intent_summary()
        source["command_intent"]["environment_variables"] = ["UV_INDEX_URL=private"]
        with self.assertRaisesRegex(ValueError, "environment overrides"):
            UvSyncIntent.from_summary(source)

    def test_typed_intent_rejects_unbounded_argv_before_runner(self) -> None:
        runner = FakeRunner(CommandRunResult(exit_code=0, stdout="", stderr=""))

        with self.assertRaisesRegex(ValueError, "bounded uv sync argv"):
            UvSyncIntent(
                request_id="uv-sync-request-unsafe",
                approval_id="approval-unsafe",
                working_directory="project",
                argv=("uv", "run", "python", "-c", "print('unsafe')"),
            )

        self.assertEqual(runner.calls, [])

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

    def test_environment_operation_module_does_not_import_implementation_candidates(
        self,
    ) -> None:
        self.assertTrue(ENVIRONMENT_OPERATION_MODULE.is_dir())
        offenders = []
        for path in ENVIRONMENT_OPERATION_MODULE.glob("*.py"):
            if "implementation_candidates" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
