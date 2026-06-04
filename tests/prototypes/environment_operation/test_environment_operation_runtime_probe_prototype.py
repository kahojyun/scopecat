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
from scopecat.environment_operation.runtime_probe import RUNTIME_PROBE_ARGV

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


def _load_tiny_uv_intent_summary() -> dict:
    return json.loads(
        (PROTOTYPE_FIXTURE / "uv-sync-intent-summary.json").read_text(encoding="utf-8")
    )


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


def _mutated_sync_result(
    result: UvSyncResult,
    *,
    intent_ref_updates: dict[str, object] | None = None,
    command_result_updates: dict[str, object] | None = None,
) -> UvSyncResult:
    intent_ref = result.intent_ref
    command_result = result.command_result
    if intent_ref_updates:
        intent_ref.update(intent_ref_updates)
    if command_result_updates:
        command_result.update(command_result_updates)
    return UvSyncResult(
        intent_ref=intent_ref,
        command_result=command_result,
        result_status=result.result_status,
        findings=result.findings,
    )


class EnvironmentOperationRuntimeProbePrototypeTest(unittest.TestCase):
    def test_builds_runtime_probe_intent_from_successful_sync_result(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        sync_result = _sync_result(sync_intent)

        probe_intent = UvRuntimeProbeIntent.from_sync_result(sync_intent, sync_result)
        request_ref = probe_intent.to_probe_request_ref()

        self.assertEqual(probe_intent.probe_request_id, f"{sync_intent.request_id}.runtime-probe")
        self.assertEqual(probe_intent.approval_id, sync_intent.approval_id)
        self.assertEqual(probe_intent.sync_result_id, sync_result.command_result["result_id"])
        self.assertEqual(probe_intent.argv, RUNTIME_PROBE_ARGV)
        self.assertEqual(len(probe_intent.argv), 7)
        self.assertEqual(probe_intent.argv[:4], ("uv", "run", "--locked", "--no-sync"))
        self.assertEqual(probe_intent.argv[4:6], ("python", "-c"))
        self.assertIn("platform.python_version()", probe_intent.argv[6])
        self.assertIn("sys.prefix != sys.base_prefix", probe_intent.argv[6])
        self.assertEqual(
            set(request_ref["command_intent"]),
            {"manager", "operation", "working_directory", "argv"},
        )
        self.assertEqual(request_ref["command_intent"]["operation"], "runtime_probe")

    def test_runtime_probe_intent_requires_successful_sync_result(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        cases = [
            CommandRunResult(exit_code=1, stdout="", stderr="sync failed"),
            subprocess.TimeoutExpired(cmd=list(sync_intent.argv), timeout=1),
            FileNotFoundError("uv executable was not found"),
        ]

        for sync_runner_result in cases:
            with self.subTest(sync_runner_result=type(sync_runner_result).__name__):
                sync_result = _sync_result(sync_intent, sync_runner_result)
                with self.assertRaisesRegex(ValueError, "successful uv sync result"):
                    UvRuntimeProbeIntent.from_sync_result(sync_intent, sync_result)

    def test_runtime_probe_intent_rejects_mismatched_sync_result(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        sync_result = _sync_result(sync_intent)
        cases = [
            _mutated_sync_result(sync_result, intent_ref_updates={"request_id": "other"}),
            _mutated_sync_result(
                sync_result,
                command_result_updates={"intent_request_id": "other"},
            ),
            _mutated_sync_result(sync_result, command_result_updates={"approval_id": "other"}),
            _mutated_sync_result(
                sync_result,
                intent_ref_updates={
                    "working_directory": "other-project",
                    "command_intent": {
                        **sync_result.intent_ref["command_intent"],
                        "working_directory": "other-project",
                    },
                },
                command_result_updates={"working_directory": "other-project"},
            ),
            _mutated_sync_result(
                sync_result,
                intent_ref_updates={
                    "command_intent": {
                        **sync_result.intent_ref["command_intent"],
                        "argv": [
                            "uv",
                            "sync",
                            "--locked",
                            "--no-default-groups",
                            "--group",
                            "extra",
                        ],
                    },
                },
                command_result_updates={
                    "argv": [
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--group",
                        "extra",
                    ]
                },
            ),
        ]

        for mismatched_result in cases:
            with self.subTest(command_result=mismatched_result.command_result):
                with self.assertRaisesRegex(ValueError, "sync result"):
                    UvRuntimeProbeIntent.from_sync_result(sync_intent, mismatched_result)

    def test_runtime_probe_intent_rejects_broadened_argv(self) -> None:
        with self.assertRaisesRegex(ValueError, "bounded probe argv"):
            UvRuntimeProbeIntent(
                probe_request_id="probe",
                approval_id="approval",
                sync_request_id="sync",
                sync_result_id="sync-result",
                working_directory="project",
                argv=("uv", "run", "python"),
            )

    def test_runtime_probe_intent_rejects_empty_typed_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "probe_request_id"):
            UvRuntimeProbeIntent(
                probe_request_id="",
                approval_id="approval",
                sync_request_id="sync",
                sync_result_id="sync-result",
                working_directory="project",
                argv=RUNTIME_PROBE_ARGV,
            )

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
                probe_result_id="uv-runtime-probe-result-001",
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
            set(summary),
            {
                "uv_runtime_probe_request_ref",
                "command_result",
                "result_status",
                "runtime_facts",
                "result_findings",
            },
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
        ).to_summary()

        self.assertNotIn("extra_secret", summary["uv_runtime_probe_request_ref"])
        self.assertNotIn(
            "extra_secret",
            summary["uv_runtime_probe_request_ref"]["command_intent"],
        )
        self.assertNotIn("raw_stdout", summary["command_result"])
        self.assertNotIn("raw_stdout", summary["command_result"]["output_capture"])

    def test_runtime_probe_result_rejects_raw_output_capture(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            result = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(
                        exit_code=0,
                        stdout=json.dumps(_runtime_facts()),
                        stderr="",
                    )
                ),
            ).to_result(probe_intent)

        command_result = result.command_result
        command_result["output_capture"]["raw_output"] = "secret raw log"

        with self.assertRaisesRegex(ValueError, "raw output must not be recorded"):
            UvRuntimeProbeResult(
                probe_request_ref=result.probe_request_ref,
                command_result=command_result,
                result_status=result.result_status,
                runtime_facts=result.runtime_facts,
                findings=result.findings,
            )

    def test_runtime_probe_result_rejects_request_command_mismatch(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            result = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(
                        exit_code=0,
                        stdout=json.dumps(_runtime_facts()),
                        stderr="",
                    )
                ),
            ).to_result(probe_intent)

        mismatches = {
            "probe_request_id": "other-probe",
            "approval_id": "other-approval",
            "sync_request_id": "other-sync",
            "sync_result_id": "other-sync-result",
            "working_directory": "other-project",
        }
        for key, value in mismatches.items():
            with self.subTest(key=key):
                command_result = result.command_result
                command_result[key] = value
                with self.assertRaisesRegex(ValueError, f"{key} must match request ref"):
                    UvRuntimeProbeResult(
                        probe_request_ref=result.probe_request_ref,
                        command_result=command_result,
                        result_status=result.result_status,
                        runtime_facts=result.runtime_facts,
                        findings=result.findings,
                    )

    def test_runtime_probe_result_rejects_inconsistent_facts_and_findings(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()
            result = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(
                        exit_code=0,
                        stdout=json.dumps(_runtime_facts()),
                        stderr="",
                    )
                ),
            ).to_result(probe_intent)

        failed_command_result = result.command_result
        failed_command_result["execution_state"] = "completed_failed"
        failed_command_result["exit_code"] = 1
        failed_command_result["stdout_summary"] = ""
        with self.assertRaisesRegex(ValueError, "runtime_facts must match command output"):
            UvRuntimeProbeResult(
                probe_request_ref=result.probe_request_ref,
                command_result=failed_command_result,
                result_status="uv_runtime_probe_completed_failed",
                runtime_facts=result.runtime_facts,
                findings=(),
            )

        system_python_facts = _runtime_facts(is_virtual_environment=False)
        system_python_facts["prefix"] = "/usr"
        system_python_facts["base_prefix"] = "/usr"
        system_python_command_result = result.command_result
        system_python_command_result["stdout_summary"] = json.dumps(system_python_facts)
        with self.assertRaisesRegex(ValueError, "findings must match"):
            UvRuntimeProbeResult(
                probe_request_ref=result.probe_request_ref,
                command_result=system_python_command_result,
                result_status=result.result_status,
                runtime_facts=system_python_facts,
                findings=(),
            )

    def test_runtime_probe_result_rejects_internally_inconsistent_runtime_facts(self) -> None:
        sync_intent = UvSyncIntent.from_summary(_load_tiny_uv_intent_summary())
        probe_intent = UvRuntimeProbeIntent.from_sync_result(
            sync_intent,
            _sync_result(sync_intent),
        )
        facts = _runtime_facts()
        facts["base_prefix"] = facts["prefix"]
        with TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            (workspace_root / "project").mkdir()

            record = execute_uv_runtime_probe(
                probe_intent,
                workspace_root=workspace_root,
                runner=FakeRunner(
                    CommandRunResult(
                        exit_code=0,
                        stdout=json.dumps(facts),
                        stderr="",
                    )
                ),
            )

        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertIsNone(record.runtime_facts)
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["runtime_probe_output_shape_invalid"],
        )

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

    def test_runtime_probe_invalid_shape_is_review_finding_not_runtime_truth(self) -> None:
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
                        stdout=json.dumps({"python_version": "3.12.8"}),
                        stderr="",
                    )
                ),
            )

        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertIsNone(record.runtime_facts)
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["runtime_probe_output_shape_invalid"],
        )

    def test_runtime_probe_truncated_stdout_is_review_finding_not_runtime_truth(self) -> None:
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
                        stdout=json.dumps(_runtime_facts()) + ("x" * 2200),
                        stderr="",
                    )
                ),
            )

        self.assertEqual(record.result_status, "uv_runtime_probe_completed_success")
        self.assertIsNone(record.runtime_facts)
        self.assertEqual(
            [finding.code for finding in record.findings],
            ["runtime_probe_stdout_truncated"],
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
