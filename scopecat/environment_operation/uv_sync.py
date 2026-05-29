"""Approved uv sync execution prototype.

This module crosses the process-execution boundary for one bounded uv command.
It does not parse dependency files or output, verify installed package state,
probe runtimes, import experiment code, contact hardware, or claim run
readiness.
"""

from __future__ import annotations

import copy
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

OUTPUT_SUMMARY_LIMIT = 2000
DEFAULT_TIMEOUT_SECONDS = 300
DEPENDENCY_GROUP = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
RESULT_STATUS_BY_EXECUTION_STATE = {
    "completed_success": "uv_sync_completed_success",
    "completed_failed": "uv_sync_completed_failed",
    "timed_out": "uv_sync_timed_out",
    "launch_failed": "uv_sync_launch_failed",
}


@dataclass(frozen=True)
class UvSyncFinding:
    """Review finding surfaced by the uv sync execution prototype."""

    code: str
    severity: str
    basis: str
    does_not_claim: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> UvSyncFinding:
        if not isinstance(value, dict):
            raise ValueError("uv sync result finding must be an object")
        return cls(
            code=_require_owned_text(value, "code", "uv sync result finding"),
            severity=_require_owned_text(value, "severity", "uv sync result finding"),
            basis=_require_owned_text(value, "basis", "uv sync result finding"),
            does_not_claim=_require_owned_text(
                value,
                "does_not_claim",
                "uv sync result finding",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "basis": self.basis,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True)
class UvSyncIntent:
    """Route-local approved uv sync command intent."""

    request_id: str
    approval_id: str
    working_directory: str
    argv: tuple[str, ...]

    @classmethod
    def from_summary(cls, summary: dict[str, Any]) -> UvSyncIntent:
        """Build a route-local intent from a validated discovery-style summary."""

        if summary.get("intent_status") != "ready_for_external_review":
            raise ValueError("uv sync intent must be ready_for_external_review")

        request = _require_mapping(summary, "sync_request")
        command = _require_mapping(summary, "command_intent")
        request_id = _require_text(request, "request_id")
        approval_id = _require_text(request, "approval_id")
        if request.get("approved_operation") != "uv_sync_intent":
            raise ValueError("sync_request must approve uv_sync_intent")
        if request.get("expected_manager") != "uv":
            raise ValueError("sync_request expected_manager must be uv")

        working_directory = _validate_relative_path(
            _require_text(request, "working_directory"),
            "working_directory",
        )
        if command.get("manager") != "uv" or command.get("operation") != "sync":
            raise ValueError("command_intent must describe uv sync")
        if command.get("working_directory") != working_directory:
            raise ValueError("command_intent working_directory must match sync_request")
        if command.get("does_not_claim") != "process_executed_or_environment_synchronized":
            raise ValueError("command_intent does_not_claim must preserve execution boundary")
        if command.get("environment_variables", []) != []:
            raise ValueError("uv sync execution prototype does not accept environment overrides")

        return cls(
            request_id=request_id,
            approval_id=approval_id,
            working_directory=working_directory,
            argv=_validate_uv_sync_argv(command.get("argv")),
        )

    def to_result_intent_ref(self) -> dict[str, Any]:
        """Return the intent projection carried by downstream result reviews."""

        return {
            "request_id": self.request_id,
            "approval_id": self.approval_id,
            "expected_manager": "uv",
            "working_directory": self.working_directory,
            "command_intent": {
                "manager": "uv",
                "operation": "sync",
                "working_directory": self.working_directory,
                "argv": list(self.argv),
                "does_not_claim": "process_executed_or_environment_synchronized",
            },
        }


@dataclass(frozen=True)
class CommandRunResult:
    """Bounded process result returned by a runner."""

    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Protocol for injectable command runners."""

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandRunResult:
        """Run a command and return captured text output."""


class SubprocessUvRunner:
    """Default runner that executes uv through subprocess."""

    def __init__(self, *, uv_executable: Path | str) -> None:
        self._uv_executable = _resolve_uv_executable(uv_executable)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandRunResult:
        launch_argv = (str(self._uv_executable), *argv[1:])
        completed = subprocess.run(
            launch_argv,
            cwd=cwd,
            env={},
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandRunResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class UvSyncExecutionRecord:
    """Review-oriented record of a Scopecat-run uv sync operation."""

    result_id: str
    intent_request_id: str
    approval_id: str
    working_directory: str
    local_execution_cwd: str
    argv: tuple[str, ...]
    execution_state: str
    exit_code: int | None
    started_at: str
    completed_at: str
    duration_ms: int
    stdout_summary: str
    stderr_summary: str
    stdout_truncated: bool
    stderr_truncated: bool
    findings: tuple[UvSyncFinding, ...]

    @property
    def result_status(self) -> str:
        return _result_status_for_execution_state(self.execution_state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_policy": {
                "operation_authority": "approved_uv_sync_execution",
                "manager_scope": "uv_only",
                "process_execution": "performed_by_scopecat_subprocess_runner",
                "output_capture": "bounded_stdout_stderr_summaries",
                "dependency_resolution": "delegated_to_uv_not_performed_by_scopecat",
                "dependency_sync_verification": "not_performed",
                "runtime_probe": "not_performed",
                "code_import_execution": "not_performed",
                "hardware_probe": "not_performed",
                "readiness_claim": "not_claimed",
            },
            "command_result": {
                "result_id": self.result_id,
                "intent_request_id": self.intent_request_id,
                "approval_id": self.approval_id,
                "manager": "uv",
                "operation": "sync",
                "working_directory": self.working_directory,
                "local_execution_cwd": self.local_execution_cwd,
                "argv": list(self.argv),
                "execution_state": self.execution_state,
                "exit_code": self.exit_code,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "duration_ms": self.duration_ms,
                "stdout_summary": self.stdout_summary,
                "stderr_summary": self.stderr_summary,
                "output_capture": {
                    "stdout": "bounded_summary",
                    "stderr": "bounded_summary",
                    "raw_output": "not_recorded",
                    "stdout_truncated": self.stdout_truncated,
                    "stderr_truncated": self.stderr_truncated,
                },
                "execution_observer": "scopecat_subprocess_executor",
            },
            "result_status": self.result_status,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_result_summary(self, intent: UvSyncIntent) -> dict[str, Any]:
        """Project execution into a route-local uv sync result summary.

        This shape is intended for downstream local review composition. It is
        route-local prototype output, not a portable/public artifact or a
        runtime-readiness result.
        """

        return UvSyncResult.from_execution(intent, self).to_summary()

    def _command_result_summary(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "intent_request_id": self.intent_request_id,
            "approval_id": self.approval_id,
            "manager": "uv",
            "operation": "sync",
            "working_directory": self.working_directory,
            "local_execution_cwd": self.local_execution_cwd,
            "argv": list(self.argv),
            "execution_state": self.execution_state,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            "output_capture": {
                "stdout": "bounded_summary",
                "stderr": "bounded_summary",
                "raw_output": "not_recorded",
                "stdout_truncated": self.stdout_truncated,
                "stderr_truncated": self.stderr_truncated,
            },
            "execution_observer": "scopecat_subprocess_executor",
        }

    def _validate_intent_alignment(self, intent: UvSyncIntent) -> None:
        if self.intent_request_id != intent.request_id:
            raise ValueError("execution record intent_request_id must match intent")
        if self.approval_id != intent.approval_id:
            raise ValueError("execution record approval_id must match intent")
        if self.working_directory != intent.working_directory:
            raise ValueError("execution record working_directory must match intent")
        if self.argv != intent.argv:
            raise ValueError("execution record argv must match intent")


@dataclass(frozen=True, init=False)
class UvSyncResult:
    """Typed route-local projection of one approved uv sync execution result."""

    _intent_ref: dict[str, Any] = field(repr=False)
    _command_result: dict[str, Any] = field(repr=False)
    result_status: str
    findings: tuple[UvSyncFinding, ...]
    _attention: tuple[dict[str, str], ...] = field(repr=False)

    def __init__(
        self,
        *,
        intent_ref: dict[str, Any],
        command_result: dict[str, Any],
        result_status: str,
        findings: tuple[UvSyncFinding, ...],
        attention: tuple[dict[str, str], ...],
    ) -> None:
        _validate_result_status(result_status)
        object.__setattr__(self, "_intent_ref", copy.deepcopy(intent_ref))
        object.__setattr__(self, "_command_result", copy.deepcopy(command_result))
        object.__setattr__(self, "result_status", result_status)
        object.__setattr__(self, "findings", _validate_typed_findings(findings))
        object.__setattr__(self, "_attention", _validate_attention(attention))

    @property
    def intent_ref(self) -> dict[str, Any]:
        return copy.deepcopy(self._intent_ref)

    @property
    def command_result(self) -> dict[str, Any]:
        return copy.deepcopy(self._command_result)

    @property
    def attention(self) -> tuple[dict[str, str], ...]:
        return tuple(copy.deepcopy(item) for item in self._attention)

    @classmethod
    def from_execution(cls, intent: UvSyncIntent, record: UvSyncExecutionRecord) -> UvSyncResult:
        """Create the typed result object from an execution record and selected intent."""

        record._validate_intent_alignment(intent)
        return cls(
            intent_ref=intent.to_result_intent_ref(),
            command_result=record._command_result_summary(),
            result_status=record.result_status,
            findings=record.findings,
            attention=tuple(_result_summary_attention()),
        )

    @classmethod
    def from_summary(cls, summary: dict[str, Any]) -> UvSyncResult:
        """Rehydrate a typed result from a route-local summary edge projection."""

        if not isinstance(summary, dict):
            raise ValueError("uv sync result summary must be an object")
        for key in (
            "uv_sync_result_policy",
            "uv_sync_intent_ref",
            "command_result",
            "result_status",
            "result_findings",
            "attention",
        ):
            if key not in summary:
                raise ValueError(f"uv sync result summary must include {key}")

        policy = _require_owned_mapping(
            summary,
            "uv_sync_result_policy",
            "uv sync result summary",
        )
        if policy != _result_summary_policy():
            raise ValueError("uv sync result summary policy must match uv sync result policy")

        result_findings = summary["result_findings"]
        if not isinstance(result_findings, list):
            raise ValueError("uv sync result summary result_findings must be a list")
        attention = summary["attention"]
        if not isinstance(attention, list) or not all(isinstance(item, dict) for item in attention):
            raise ValueError("uv sync result summary attention must be a list of objects")
        if attention != _result_summary_attention():
            raise ValueError("uv sync result summary attention must match uv sync result attention")

        intent_ref = _require_owned_mapping(
            summary,
            "uv_sync_intent_ref",
            "uv sync result summary",
        )
        command_result = _require_owned_mapping(
            summary,
            "command_result",
            "uv sync result summary",
        )
        result_status = _require_owned_text(
            summary,
            "result_status",
            "uv sync result summary",
        )
        findings = tuple(UvSyncFinding.from_dict(item) for item in result_findings)
        _validate_summary_command_result(command_result)
        _validate_summary_consistency(command_result, result_status, findings)

        return cls(
            intent_ref=intent_ref,
            command_result=command_result,
            result_status=result_status,
            findings=findings,
            attention=tuple(copy.deepcopy(item) for item in attention),
        )

    def to_summary(self) -> dict[str, Any]:
        """Project this typed result into the route-local review summary shape."""

        return {
            "uv_sync_result_policy": _result_summary_policy(),
            "uv_sync_intent_ref": self.intent_ref,
            "command_result": self.command_result,
            "result_status": self.result_status,
            "result_findings": [finding.to_dict() for finding in self.findings],
            "attention": [copy.deepcopy(item) for item in self._attention],
        }


def execute_uv_sync(
    intent: UvSyncIntent,
    *,
    workspace_root: Path,
    result_id: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: CommandRunner | None = None,
    uv_executable: Path | str | None = None,
) -> UvSyncExecutionRecord:
    """Execute an approved uv sync intent under a caller-provided workspace root."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    command_cwd = _command_cwd(workspace_root, intent.working_directory)
    started = datetime.now(UTC)

    try:
        runner = runner or _default_subprocess_runner(uv_executable)
        run_result = runner.run(
            intent.argv,
            cwd=command_cwd,
            timeout_seconds=timeout_seconds,
        )
        completed = datetime.now(UTC)
        execution_state = "completed_success" if run_result.exit_code == 0 else "completed_failed"
        exit_code: int | None = run_result.exit_code
        stdout = run_result.stdout
        stderr = run_result.stderr
    except subprocess.TimeoutExpired as exc:
        completed = datetime.now(UTC)
        execution_state = "timed_out"
        exit_code = None
        stdout = _coerce_timeout_output(exc.stdout)
        stderr = _coerce_timeout_output(exc.stderr)
    except OSError as exc:
        completed = datetime.now(UTC)
        execution_state = "launch_failed"
        exit_code = None
        stdout = ""
        stderr = str(exc)

    stdout_summary, stdout_truncated = _summarize_output(stdout)
    stderr_summary, stderr_truncated = _summarize_output(stderr)
    return UvSyncExecutionRecord(
        result_id=result_id or f"{intent.request_id}.execution",
        intent_request_id=intent.request_id,
        approval_id=intent.approval_id,
        working_directory=intent.working_directory,
        local_execution_cwd=str(command_cwd),
        argv=intent.argv,
        execution_state=execution_state,
        exit_code=exit_code,
        started_at=_format_instant(started),
        completed_at=_format_instant(completed),
        duration_ms=max(0, int((completed - started).total_seconds() * 1000)),
        stdout_summary=stdout_summary,
        stderr_summary=stderr_summary,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        findings=tuple(_findings(execution_state)),
    )


def _command_cwd(workspace_root: Path, working_directory: str) -> Path:
    root = workspace_root.resolve()
    if not root.is_dir():
        raise ValueError("workspace_root must exist and be a directory")
    candidate = (root / working_directory).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("working_directory must stay under workspace_root")
    if not candidate.is_dir():
        raise ValueError("working_directory must exist under workspace_root")
    return candidate


def _findings(execution_state: str) -> list[UvSyncFinding]:
    if execution_state == "completed_failed":
        return [
            UvSyncFinding(
                code="uv_sync_process_failed",
                severity="review",
                basis="The Scopecat-run uv sync process exited with a non-zero status.",
                does_not_claim="synchronized_or_installed_environment",
            )
        ]
    if execution_state == "timed_out":
        return [
            UvSyncFinding(
                code="uv_sync_process_timed_out",
                severity="review",
                basis="The Scopecat-run uv sync process exceeded the approved timeout.",
                does_not_claim="synchronized_or_installed_environment",
            )
        ]
    if execution_state == "launch_failed":
        return [
            UvSyncFinding(
                code="uv_sync_process_launch_failed",
                severity="review",
                basis="The Scopecat uv sync subprocess could not be launched.",
                does_not_claim="manager_available_or_environment_synchronized",
            )
        ]
    return []


def _result_summary_attention() -> list[dict[str, str]]:
    return [
        {
            "code": "uv_sync_executed_by_scopecat",
            "severity": "review",
            "basis": "Scopecat launched the approved uv sync command through a local subprocess.",
            "does_not_claim": "verified_synchronized_environment",
        },
        {
            "code": "bounded_output_summary_only",
            "severity": "review",
            "basis": "stdout and stderr are retained as bounded summaries, not raw logs.",
            "does_not_claim": "dependency_graph_or_package_change_set",
        },
        {
            "code": "runnable_readiness_not_claimed",
            "severity": "review",
            "basis": "The execution result does not inspect interpreters, packages, or experiment code.",
            "does_not_claim": "run_can_start",
        },
    ]


def _result_summary_policy() -> dict[str, str]:
    return {
        "summary_policy": "review_summary",
        "result_authority": "scopecat_uv_sync_execution_result",
        "prior_intent_source": "route_local_uv_sync_intent",
        "manager_scope": "uv_only",
        "command_result_shape": "bounded_uv_sync_execution_record",
        "local_execution_cwd_authority": "local_review_path_internal",
        "scopecat_process_execution": "performed",
        "manifest_read": "not_performed",
        "lockfile_read": "not_performed",
        "output_parsing": "summary_only_no_dependency_parsing",
        "dependency_resolution": "delegated_to_uv_not_performed_by_scopecat",
        "dependency_sync": "manager_result_not_verified_by_scopecat",
        "package_install": "manager_result_not_verified_by_scopecat",
        "runtime_probe": "not_performed",
        "code_import_execution": "not_performed",
        "hardware_probe": "not_performed",
        "readiness_claim": "not_claimed",
        "shared_environment_schema": "not_defined",
    }


def _result_status_for_execution_state(execution_state: str) -> str:
    try:
        return RESULT_STATUS_BY_EXECUTION_STATE[execution_state]
    except KeyError as exc:
        raise ValueError("uv sync execution_state must be recognized") from exc


def _validate_result_status(value: str) -> None:
    if value not in RESULT_STATUS_BY_EXECUTION_STATE.values():
        raise ValueError("uv sync result_status must be recognized")


def _validate_typed_findings(
    findings: tuple[UvSyncFinding, ...],
) -> tuple[UvSyncFinding, ...]:
    validated = tuple(findings)
    if not all(isinstance(finding, UvSyncFinding) for finding in validated):
        raise ValueError("uv sync result findings must be UvSyncFinding objects")
    return validated


def _validate_attention(
    attention: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    validated = tuple(copy.deepcopy(item) for item in attention)
    for item in validated:
        if not isinstance(item, dict):
            raise ValueError("uv sync result attention entries must be objects")
        for key in ("code", "severity", "basis", "does_not_claim"):
            _require_owned_text(item, key, "uv sync result attention")
    return validated


def _validate_summary_command_result(command_result: dict[str, Any]) -> None:
    if _require_owned_text(command_result, "manager", "uv sync command result") != "uv":
        raise ValueError("uv sync command result manager must be uv")
    if _require_owned_text(command_result, "operation", "uv sync command result") != "sync":
        raise ValueError("uv sync command result operation must be sync")
    _validate_uv_sync_argv(command_result.get("argv"))
    _require_owned_text(command_result, "result_id", "uv sync command result")
    _require_owned_text(command_result, "intent_request_id", "uv sync command result")
    _require_owned_text(command_result, "approval_id", "uv sync command result")
    _validate_relative_path(
        _require_owned_text(command_result, "working_directory", "uv sync command result"),
        "uv sync command result working_directory",
    )


def _validate_summary_consistency(
    command_result: dict[str, Any],
    result_status: str,
    findings: tuple[UvSyncFinding, ...],
) -> None:
    execution_state = _require_owned_text(
        command_result,
        "execution_state",
        "uv sync command result",
    )
    expected_status = _result_status_for_execution_state(execution_state)
    if result_status != expected_status:
        raise ValueError("uv sync result_status must match execution_state")

    exit_code = command_result.get("exit_code")
    if execution_state == "completed_success" and exit_code != 0:
        raise ValueError("completed uv sync success must have exit_code 0")
    if execution_state == "completed_failed" and (not isinstance(exit_code, int) or exit_code == 0):
        raise ValueError("failed uv sync process must have non-zero exit_code")
    if execution_state in {"timed_out", "launch_failed"} and exit_code is not None:
        raise ValueError("non-completed uv sync process must not have exit_code")

    expected_findings = tuple(_findings(execution_state))
    if tuple(finding.to_dict() for finding in findings) != tuple(
        finding.to_dict() for finding in expected_findings
    ):
        raise ValueError("uv sync result_findings must match execution_state")


def _validate_relative_path(value: str, owner: str) -> str:
    if value == ".":
        return value
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"{owner} must be a relative workspace path")
    return value


def _validate_uv_sync_argv(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("command_intent argv must be a list of strings")
    argv = tuple(value)
    if len(argv) < 4 or argv[:4] != ("uv", "sync", "--locked", "--no-default-groups"):
        raise ValueError("command_intent argv must be bounded uv sync argv")

    remaining = argv[4:]
    if len(remaining) % 2 != 0:
        raise ValueError("command_intent argv groups must use --group name pairs")
    for index in range(0, len(remaining), 2):
        if remaining[index] != "--group" or not _valid_group_name(remaining[index + 1]):
            raise ValueError("command_intent argv groups must use --group name pairs")
    return argv


def _valid_group_name(value: str) -> bool:
    return bool(DEPENDENCY_GROUP.fullmatch(value))


def _default_subprocess_runner(uv_executable: Path | str | None) -> SubprocessUvRunner:
    if uv_executable is None:
        raise ValueError("uv_executable is required when runner is not provided")
    return SubprocessUvRunner(uv_executable=uv_executable)


def _resolve_uv_executable(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("uv_executable must be an absolute path")
    return path.resolve()


def _require_mapping(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be text")
    return value


def _require_owned_mapping(source: dict[str, Any], key: str, owner: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{owner} {key} must be an object")
    return copy.deepcopy(value)


def _require_owned_text(source: dict[str, Any], key: str, owner: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} {key} must be text")
    return value


def _summarize_output(output: str) -> tuple[str, bool]:
    normalized = output.strip()
    if len(normalized) <= OUTPUT_SUMMARY_LIMIT:
        return normalized, False
    return normalized[:OUTPUT_SUMMARY_LIMIT], True


def _coerce_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _format_instant(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
