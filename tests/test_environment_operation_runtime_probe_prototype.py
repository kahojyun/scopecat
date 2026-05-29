from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scopecat.environment_operation import (
    CommandRunResult,
    UvRuntimeProbeIntent,
    UvRuntimeProbeResult,
    UvSyncIntent,
    UvSyncResult,
    execute_uv_runtime_probe,
    execute_uv_sync,
)

ROOT = Path(__file__).resolve().parents[1]
INTENT_FIXTURE = ROOT / "tests" / "fixtures" / "uv_sync_intent" / "basic_uv_sync_intent"
TINY_UV_WORKSPACE = (
    ROOT / "tests" / "fixtures" / "environment_operation_execution" / "tiny_uv_workspace"
)


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


def _sync_result(
    intent: UvSyncIntent,
    result: CommandRunResult | BaseException = CommandRunResult(
        exit_code=0,
        stdout="sync ok",
        stderr="",
    ),
) -> UvSyncResult:
    with TemporaryDirectory() as tmp:
        workspace_root = Path(tmp)
        (workspace_root / "project").mkdir()
        record = execute_uv_sync(
            intent,
            workspace_root=workspace_root,
            result_id="uv-sync-result-runtime-probe-source-001",
            runner=FakeRunner(result),
        )
    return UvSyncResult.from_execution(intent, record)


def _runtime_facts(*, is_virtual_environment: bool = True) -> dict[str, object]:
    return {
        "python_version": "3.12.8",
        "python_implementation": "CPython",
        "executable": "/workspace/project/.venv/bin/python",
        "prefix": "/workspace/project/.venv",
        "base_prefix": "/opt/python/3.12",
        "is_virtual_environment": is_virtual_environment,
    }


class EnvironmentOperationRuntimeProbePrototypeTest(unittest.TestCase):
    def test_builds_runtime_probe_intent_from_successful_sync_result(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        sync_result = _sync_result(sync_intent)

        probe_intent = UvRuntimeProbeIntent.from_sync_result(sync_intent, sync_result)
        request_ref = probe_intent.to_probe_request_ref()

        self.assertEqual(probe_intent.probe_request_id, f"{sync_intent.request_id}.runtime-probe")
        self.assertEqual(probe_intent.approval_id, sync_intent.approval_id)
        self.assertEqual(probe_intent.sync_result_id, sync_result.command_result["result_id"])
        self.assertEqual(probe_intent.argv[:4], ("uv", "run", "--locked", "--no-sync"))
        self.assertEqual(probe_intent.argv[4:6], ("python", "-c"))
        self.assertEqual(
            request_ref["command_intent"]["does_not_claim"],
            "experiment_code_executed_or_run_readiness",
        )

    def test_runtime_probe_intent_requires_successful_sync_result(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        failed_sync_result = _sync_result(
            sync_intent,
            CommandRunResult(exit_code=1, stdout="", stderr="sync failed"),
        )

        with self.assertRaisesRegex(ValueError, "successful uv sync result"):
            UvRuntimeProbeIntent.from_sync_result(sync_intent, failed_sync_result)

    def test_executes_runtime_probe_through_injected_runner(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        runner = FakeRunner(
            CommandRunResult(
                exit_code=0,
                stdout=json.dumps(_runtime_facts()),
                stderr="",
            )
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            project = workspace_root / "project"
            project.mkdir()

            record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                probe_result_id="uv-runtime-probe-result-chevron-qA-001",
                timeout_seconds=19,
                runner=runner,
            )

        self.assertEqual(
            runner.calls,
            [{"argv": probe_intent.argv, "cwd": project.resolve(), "timeout_seconds": 19}],
        )
        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertEqual(record.execution_state, "completed_success")
        self.assertEqual(record.findings, ())
        self.assertEqual(record.runtime_facts, _runtime_facts())

        summary = record.to_summary(probe_intent)
        self.assertEqual(
            summary["uv_runtime_probe_result_policy"]["environment_sync"],
            "disabled_with_uv_run_no_sync",
        )
        self.assertEqual(
            summary["uv_runtime_probe_result_policy"]["readiness_claim"],
            "not_claimed",
        )
        self.assertEqual(summary["runtime_facts"]["is_virtual_environment"], True)
        self.assertEqual(summary["command_result"]["output_capture"]["raw_output"], "not_recorded")

    def test_successful_probe_that_reports_system_python_is_review_finding(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        facts = _runtime_facts(is_virtual_environment=False)
        facts["prefix"] = "/usr"
        facts["base_prefix"] = "/usr"
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(exit_code=0, stdout=json.dumps(facts), stderr="")
                ),
            )

        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["runtime_probe_not_virtual_environment"],
        )
        self.assertEqual(
            record.findings[0].does_not_claim,
            "project_virtual_environment_used",
        )

    def test_runtime_probe_summary_does_not_leak_extra_constructor_fields(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(
                        exit_code=0,
                        stdout=json.dumps(_runtime_facts()),
                        stderr="",
                    )
                ),
            )

        result = record.to_result(probe_intent)
        probe_request_ref = result.probe_request_ref
        command_result = result.command_result
        probe_request_ref["extra_secret"] = "not exported"
        probe_request_ref["command_intent"]["extra_secret"] = "not exported"
        command_result["raw_stdout"] = "not exported"
        command_result["output_capture"]["raw_stdout"] = "not exported"

        summary = UvRuntimeProbeResult(
            probe_request_ref=probe_request_ref,
            command_result=command_result,
            result_status=result.result_status,
            runtime_facts=result.runtime_facts,
            findings=result.findings,
            attention=result.attention,
        ).to_summary()

        self.assertNotIn("extra_secret", summary["uv_runtime_probe_request_ref"])
        self.assertNotIn(
            "extra_secret",
            summary["uv_runtime_probe_request_ref"]["command_intent"],
        )
        self.assertNotIn("raw_stdout", summary["command_result"])
        self.assertNotIn("raw_stdout", summary["command_result"]["output_capture"])

    def test_runtime_probe_failure_timeout_and_launch_failure_are_review_findings(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        cases = [
            (
                CommandRunResult(exit_code=1, stdout="", stderr="probe failed"),
                "uv_runtime_probe_completed_failed",
                "uv_runtime_probe_process_failed",
            ),
            (
                subprocess.TimeoutExpired(
                    cmd=list(probe_intent.argv),
                    timeout=1,
                    output="partial",
                    stderr="timed out",
                ),
                "uv_runtime_probe_timed_out",
                "uv_runtime_probe_process_timed_out",
            ),
            (
                FileNotFoundError("uv executable was not found"),
                "uv_runtime_probe_launch_failed",
                "uv_runtime_probe_process_launch_failed",
            ),
        ]

        for runner_result, result_status, finding_code in cases:
            with self.subTest(result_status=result_status), TemporaryDirectory() as tmp:
                workspace_root = Path(tmp)
                (workspace_root / "project").mkdir()

                record = execute_uv_runtime_probe(
                    probe_intent,
                    workspace_root=workspace_root,
                    runner=FakeRunner(runner_result),
                )

                self.assertEqual(record.result_status, result_status)
                self.assertEqual([finding.code for finding in record.findings], [finding_code])
                self.assertIsNone(record.runtime_facts)

    def test_runtime_probe_invalid_json_is_review_finding_not_runtime_truth(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(CommandRunResult(exit_code=0, stdout="not json", stderr="")),
            )

        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertIsNone(record.runtime_facts)
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["runtime_probe_output_not_json"],
        )

    def test_executes_real_runtime_probe_after_real_uv_sync_fixture(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            shutil.copytree(TINY_UV_WORKSPACE, workspace_root)

            sync_record = execute_uv_sync(
                sync_intent,
                workspace_root=workspace_root,
                result_id="uv-sync-result-runtime-probe-real-001",
                timeout_seconds=60,
                uv_executable=_uv_executable(),
            )
            probe_intent = UvRuntimeProbeIntent.from_sync_result(
                sync_intent,
                UvSyncResult.from_execution(sync_intent, sync_record),
            )
            probe_record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                probe_result_id="uv-runtime-probe-result-real-001",
                timeout_seconds=60,
                uv_executable=_uv_executable(),
            )

        self.assertEqual(probe_record.result_status, "uv_runtime_probe_completed_success")
        self.assertEqual(probe_record.execution_state, "completed_success")
        self.assertIsNotNone(probe_record.runtime_facts)
        assert probe_record.runtime_facts is not None
        self.assertTrue(probe_record.runtime_facts["is_virtual_environment"])
        self.assertEqual(probe_record.findings, ())


if __name__ == "__main__":
    unittest.main()
