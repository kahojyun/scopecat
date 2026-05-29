"""Post-sync uv runtime probe prototype.

This module probes one bounded Python interpreter fact surface through
``uv run --locked --no-sync`` after an approved uv sync result. It does not
import experiment code, inspect packages broadly, contact hardware, or decide
run readiness.
"""

from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scopecat.environment_operation.uv_sync import (
    DEFAULT_TIMEOUT_SECONDS,
    CommandRunner,
    UvSyncIntent,
    UvSyncResult,
    _coerce_timeout_output,
    _command_cwd,
    _default_subprocess_runner,
    _format_instant,
    _require_bool,
    _require_mapping,
    _require_text,
    _summarize_output,
    _validate_non_empty_text,
    _validate_relative_path,
)

RUNTIME_PROBE_SCRIPT = (
    "import json, platform, sys; "
    "print(json.dumps({"
    "'python_version': platform.python_version(), "
    "'python_implementation': platform.python_implementation(), "
    "'executable': sys.executable, "
    "'prefix': sys.prefix, "
    "'base_prefix': sys.base_prefix, "
    "'is_virtual_environment': sys.prefix != sys.base_prefix"
    "}, sort_keys=True))"
)
RUNTIME_PROBE_ARGV = (
    "uv",
    "run",
    "--locked",
    "--no-sync",
    "python",
    "-c",
    RUNTIME_PROBE_SCRIPT,
)

RUNTIME_PROBE_STATUS_BY_EXECUTION_STATE = {
    "completed_success": "uv_runtime_probe_completed_success",
    "completed_failed": "uv_runtime_probe_completed_failed",
    "timed_out": "uv_runtime_probe_timed_out",
    "launch_failed": "uv_runtime_probe_launch_failed",
}


@dataclass(frozen=True)
class UvRuntimeProbeFinding:
    """Review finding surfaced by the uv runtime probe prototype."""

    code: str
    severity: str
    basis: str
    does_not_claim: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "basis": self.basis,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True)
class UvRuntimeProbeIntent:
    """Route-local approved uv runtime probe command intent."""

    probe_request_id: str
    approval_id: str
    sync_request_id: str
    sync_result_id: str
    working_directory: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_non_empty_text(
            self.probe_request_id,
            "uv runtime probe intent probe_request_id",
        )
        _validate_non_empty_text(
            self.approval_id,
            "uv runtime probe intent approval_id",
        )
        _validate_non_empty_text(
            self.sync_request_id,
            "uv runtime probe intent sync_request_id",
        )
        _validate_non_empty_text(
            self.sync_result_id,
            "uv runtime probe intent sync_result_id",
        )
        if self.argv != RUNTIME_PROBE_ARGV:
            raise ValueError("runtime probe intent argv must be bounded probe argv")
        _validate_relative_path(
            self.working_directory,
            "uv runtime probe intent working_directory",
        )

    @classmethod
    def from_sync_result(
        cls,
        sync_intent: UvSyncIntent,
        sync_result: UvSyncResult,
    ) -> UvRuntimeProbeIntent:
        """Build a bounded runtime probe intent from a successful sync result."""

        _validate_sync_result_alignment(sync_intent, sync_result)
        if sync_result.result_status != "uv_sync_completed_success" or sync_result.findings:
            raise ValueError("runtime probe requires a successful uv sync result")
        command_result = sync_result.command_result
        return cls(
            probe_request_id=f"{sync_intent.request_id}.runtime-probe",
            approval_id=sync_intent.approval_id,
            sync_request_id=sync_intent.request_id,
            sync_result_id=_require_text(command_result, "result_id"),
            working_directory=sync_intent.working_directory,
            argv=RUNTIME_PROBE_ARGV,
        )

    def to_probe_request_ref(self) -> dict[str, Any]:
        return {
            "probe_request_id": self.probe_request_id,
            "approval_id": self.approval_id,
            "sync_request_id": self.sync_request_id,
            "sync_result_id": self.sync_result_id,
            "expected_manager": "uv",
            "working_directory": self.working_directory,
            "command_intent": {
                "manager": "uv",
                "operation": "runtime_probe",
                "working_directory": self.working_directory,
                "argv": list(self.argv),
                "does_not_claim": "experiment_code_executed_or_run_readiness",
            },
        }


@dataclass(frozen=True)
class UvRuntimeProbeExecutionRecord:
    """Review-oriented record of a Scopecat-run uv runtime probe."""

    probe_result_id: str
    probe_request_id: str
    approval_id: str
    sync_request_id: str
    sync_result_id: str
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
    runtime_facts: dict[str, Any] | None
    findings: tuple[UvRuntimeProbeFinding, ...]

    @property
    def result_status(self) -> str:
        return _runtime_probe_status_for_execution_state(self.execution_state)

    def to_result(self, intent: UvRuntimeProbeIntent) -> UvRuntimeProbeResult:
        return UvRuntimeProbeResult.from_execution(intent, self)

    def to_summary(self, intent: UvRuntimeProbeIntent) -> dict[str, Any]:
        return self.to_result(intent).to_summary()

    def _command_result_summary(self) -> dict[str, Any]:
        return {
            "probe_result_id": self.probe_result_id,
            "probe_request_id": self.probe_request_id,
            "approval_id": self.approval_id,
            "sync_request_id": self.sync_request_id,
            "sync_result_id": self.sync_result_id,
            "manager": "uv",
            "operation": "runtime_probe",
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

    def _validate_intent_alignment(self, intent: UvRuntimeProbeIntent) -> None:
        if self.probe_request_id != intent.probe_request_id:
            raise ValueError("runtime probe record probe_request_id must match intent")
        if self.approval_id != intent.approval_id:
            raise ValueError("runtime probe record approval_id must match intent")
        if self.sync_request_id != intent.sync_request_id:
            raise ValueError("runtime probe record sync_request_id must match intent")
        if self.sync_result_id != intent.sync_result_id:
            raise ValueError("runtime probe record sync_result_id must match intent")
        if self.working_directory != intent.working_directory:
            raise ValueError("runtime probe record working_directory must match intent")
        if self.argv != intent.argv:
            raise ValueError("runtime probe record argv must match intent")


@dataclass(frozen=True, init=False)
class UvRuntimeProbeResult:
    """Typed route-local projection of one uv runtime probe execution result."""

    _probe_request_ref: dict[str, Any] = field(repr=False)
    _command_result: dict[str, Any] = field(repr=False)
    result_status: str
    _runtime_facts: dict[str, Any] | None = field(repr=False)
    findings: tuple[UvRuntimeProbeFinding, ...]
    _attention: tuple[dict[str, str], ...] = field(repr=False)

    def __init__(
        self,
        *,
        probe_request_ref: dict[str, Any],
        command_result: dict[str, Any],
        result_status: str,
        runtime_facts: dict[str, Any] | None,
        findings: tuple[UvRuntimeProbeFinding, ...],
        attention: tuple[dict[str, str], ...],
    ) -> None:
        coerced_command_result = _coerce_probe_command_result(command_result)
        coerced_probe_request_ref = _coerce_probe_request_ref(probe_request_ref)
        coerced_runtime_facts = _coerce_runtime_facts(runtime_facts)
        coerced_findings = _validate_probe_findings(findings)
        _validate_probe_result_request_alignment(
            coerced_probe_request_ref,
            coerced_command_result,
        )
        _validate_probe_result_consistency(
            coerced_command_result,
            result_status,
            coerced_runtime_facts,
            coerced_findings,
        )
        object.__setattr__(
            self,
            "_probe_request_ref",
            coerced_probe_request_ref,
        )
        object.__setattr__(self, "_command_result", coerced_command_result)
        object.__setattr__(self, "result_status", result_status)
        object.__setattr__(self, "_runtime_facts", coerced_runtime_facts)
        object.__setattr__(self, "findings", coerced_findings)
        object.__setattr__(self, "_attention", _validate_attention(attention))

    @property
    def probe_request_ref(self) -> dict[str, Any]:
        return copy.deepcopy(self._probe_request_ref)

    @property
    def command_result(self) -> dict[str, Any]:
        return copy.deepcopy(self._command_result)

    @property
    def runtime_facts(self) -> dict[str, Any] | None:
        if self._runtime_facts is None:
            return None
        return copy.deepcopy(self._runtime_facts)

    @property
    def attention(self) -> tuple[dict[str, str], ...]:
        return tuple(copy.deepcopy(item) for item in self._attention)

    @classmethod
    def from_execution(
        cls,
        intent: UvRuntimeProbeIntent,
        record: UvRuntimeProbeExecutionRecord,
    ) -> UvRuntimeProbeResult:
        record._validate_intent_alignment(intent)
        return cls(
            probe_request_ref=intent.to_probe_request_ref(),
            command_result=record._command_result_summary(),
            result_status=record.result_status,
            runtime_facts=record.runtime_facts,
            findings=record.findings,
            attention=tuple(_runtime_probe_attention()),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "uv_runtime_probe_result_policy": {
                "summary_policy": "review_summary",
                "result_authority": "scopecat_uv_runtime_probe_result",
                "prior_sync_result_source": "route_local_uv_sync_result",
                "manager_scope": "uv_only",
                "command_result_shape": "bounded_uv_runtime_probe_execution_record",
                "local_path_authority": "local_review_path_internal",
                "runtime_path_authority": "local_review_path_internal",
                "scopecat_process_execution": "performed",
                "uv_sync": "not_performed_by_probe",
                "lockfile_update": "not_performed",
                "environment_sync": "disabled_with_uv_run_no_sync",
                "package_state_verification": "not_performed",
                "experiment_code_import": "not_performed",
                "experiment_code_execution": "not_performed",
                "hardware_probe": "not_performed",
                "readiness_claim": "not_claimed",
            },
            "uv_runtime_probe_request_ref": self.probe_request_ref,
            "command_result": self.command_result,
            "result_status": self.result_status,
            "runtime_facts": self.runtime_facts,
            "result_findings": [finding.to_dict() for finding in self.findings],
            "attention": [copy.deepcopy(item) for item in self._attention],
        }


def execute_uv_runtime_probe(
    intent: UvRuntimeProbeIntent,
    *,
    workspace_root: Path,
    probe_result_id: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: CommandRunner | None = None,
    uv_executable: Path | str | None = None,
) -> UvRuntimeProbeExecutionRecord:
    """Execute one bounded uv runtime probe under a caller-provided workspace root."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if intent.argv != RUNTIME_PROBE_ARGV:
        raise ValueError("runtime probe intent argv must be bounded probe argv")

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
    runtime_facts, parse_findings = _runtime_facts_from_stdout(
        stdout_summary,
        execution_state,
        stdout_truncated,
    )
    findings = tuple(
        [
            *_runtime_probe_findings(execution_state),
            *parse_findings,
            *_runtime_fact_findings(runtime_facts),
        ]
    )
    return UvRuntimeProbeExecutionRecord(
        probe_result_id=probe_result_id or f"{intent.probe_request_id}.execution",
        probe_request_id=intent.probe_request_id,
        approval_id=intent.approval_id,
        sync_request_id=intent.sync_request_id,
        sync_result_id=intent.sync_result_id,
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
        runtime_facts=runtime_facts,
        findings=findings,
    )


def _validate_sync_result_alignment(sync_intent: UvSyncIntent, sync_result: UvSyncResult) -> None:
    intent_ref = sync_result.intent_ref
    command_result = sync_result.command_result
    if intent_ref != sync_intent.to_result_intent_ref():
        raise ValueError("runtime probe sync result intent_ref must match sync intent")
    if command_result["intent_request_id"] != sync_intent.request_id:
        raise ValueError("runtime probe sync result must reference sync intent")
    if command_result["approval_id"] != sync_intent.approval_id:
        raise ValueError("runtime probe sync result approval_id must match sync intent")
    if command_result["working_directory"] != sync_intent.working_directory:
        raise ValueError("runtime probe sync result working_directory must match sync intent")
    if tuple(command_result["argv"]) != sync_intent.argv:
        raise ValueError("runtime probe sync result argv must match sync intent")


def _runtime_facts_from_stdout(
    stdout_summary: str,
    execution_state: str,
    stdout_truncated: bool,
) -> tuple[dict[str, Any] | None, list[UvRuntimeProbeFinding]]:
    if execution_state != "completed_success":
        return None, []
    if stdout_truncated:
        return None, [
            UvRuntimeProbeFinding(
                code="runtime_probe_stdout_truncated",
                severity="review",
                basis="The runtime probe stdout was truncated before JSON facts could be trusted.",
                does_not_claim="complete_runtime_probe_facts",
            )
        ]
    try:
        parsed = json.loads(stdout_summary)
    except json.JSONDecodeError:
        return None, [
            UvRuntimeProbeFinding(
                code="runtime_probe_output_not_json",
                severity="review",
                basis="The runtime probe command completed but did not emit valid JSON facts.",
                does_not_claim="runtime_facts_observed",
            )
        ]
    try:
        return _coerce_runtime_facts(parsed), []
    except ValueError as exc:
        return None, [
            UvRuntimeProbeFinding(
                code="runtime_probe_output_shape_invalid",
                severity="review",
                basis=str(exc),
                does_not_claim="runtime_facts_observed",
            )
        ]


def _coerce_runtime_facts(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("runtime_facts must be an object")
    facts = {
        "python_version": _require_text(value, "python_version"),
        "python_implementation": _require_text(value, "python_implementation"),
        "executable": _require_text(value, "executable"),
        "prefix": _require_text(value, "prefix"),
        "base_prefix": _require_text(value, "base_prefix"),
        "is_virtual_environment": _require_bool(value, "is_virtual_environment"),
    }
    if facts["is_virtual_environment"] != (facts["prefix"] != facts["base_prefix"]):
        raise ValueError("runtime_facts virtual environment flag must match prefix facts")
    return facts


def _coerce_probe_request_ref(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("uv runtime probe request ref must be an object")
    command_intent = _require_mapping(value, "command_intent")
    working_directory = _validate_relative_path(
        _require_text(value, "working_directory"),
        "uv runtime probe request working_directory",
    )
    command_working_directory = _validate_relative_path(
        _require_text(command_intent, "working_directory"),
        "uv runtime probe command working_directory",
    )
    if _require_text(value, "expected_manager") != "uv":
        raise ValueError("uv runtime probe request expected_manager must be uv")
    if _require_text(command_intent, "manager") != "uv":
        raise ValueError("uv runtime probe command manager must be uv")
    if _require_text(command_intent, "operation") != "runtime_probe":
        raise ValueError("uv runtime probe command operation must be runtime_probe")
    if command_working_directory != working_directory:
        raise ValueError("uv runtime probe command working_directory must match request")
    if tuple(command_intent.get("argv", ())) != RUNTIME_PROBE_ARGV:
        raise ValueError("uv runtime probe command argv must be bounded probe argv")
    if _require_text(command_intent, "does_not_claim") != (
        "experiment_code_executed_or_run_readiness"
    ):
        raise ValueError("uv runtime probe command does_not_claim must preserve boundary")
    return {
        "probe_request_id": _validate_non_empty_text(
            _require_text(value, "probe_request_id"),
            "uv runtime probe request probe_request_id",
        ),
        "approval_id": _validate_non_empty_text(
            _require_text(value, "approval_id"),
            "uv runtime probe request approval_id",
        ),
        "sync_request_id": _validate_non_empty_text(
            _require_text(value, "sync_request_id"),
            "uv runtime probe request sync_request_id",
        ),
        "sync_result_id": _validate_non_empty_text(
            _require_text(value, "sync_result_id"),
            "uv runtime probe request sync_result_id",
        ),
        "expected_manager": "uv",
        "working_directory": working_directory,
        "command_intent": {
            "manager": "uv",
            "operation": "runtime_probe",
            "working_directory": working_directory,
            "argv": list(RUNTIME_PROBE_ARGV),
            "does_not_claim": "experiment_code_executed_or_run_readiness",
        },
    }


def _coerce_probe_command_result(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("uv runtime probe command_result must be an object")
    if _require_text(value, "manager") != "uv":
        raise ValueError("uv runtime probe command_result manager must be uv")
    if _require_text(value, "operation") != "runtime_probe":
        raise ValueError("uv runtime probe command_result operation must be runtime_probe")
    if tuple(value.get("argv", ())) != RUNTIME_PROBE_ARGV:
        raise ValueError("uv runtime probe command_result argv must be bounded probe argv")
    output_capture = _require_mapping(value, "output_capture")
    if output_capture.get("stdout") != "bounded_summary":
        raise ValueError("uv runtime probe stdout capture must be bounded_summary")
    if output_capture.get("stderr") != "bounded_summary":
        raise ValueError("uv runtime probe stderr capture must be bounded_summary")
    if output_capture.get("raw_output") != "not_recorded":
        raise ValueError("uv runtime probe raw output must not be recorded")
    if _require_text(value, "execution_observer") != "scopecat_subprocess_executor":
        raise ValueError("uv runtime probe execution_observer must be Scopecat")
    return {
        "probe_result_id": _validate_non_empty_text(
            _require_text(value, "probe_result_id"),
            "uv runtime probe command_result probe_result_id",
        ),
        "probe_request_id": _validate_non_empty_text(
            _require_text(value, "probe_request_id"),
            "uv runtime probe command_result probe_request_id",
        ),
        "approval_id": _validate_non_empty_text(
            _require_text(value, "approval_id"),
            "uv runtime probe command_result approval_id",
        ),
        "sync_request_id": _validate_non_empty_text(
            _require_text(value, "sync_request_id"),
            "uv runtime probe command_result sync_request_id",
        ),
        "sync_result_id": _validate_non_empty_text(
            _require_text(value, "sync_result_id"),
            "uv runtime probe command_result sync_result_id",
        ),
        "manager": "uv",
        "operation": "runtime_probe",
        "working_directory": _validate_relative_path(
            _require_text(value, "working_directory"),
            "uv runtime probe command_result working_directory",
        ),
        "local_execution_cwd": _require_text(value, "local_execution_cwd"),
        "argv": list(RUNTIME_PROBE_ARGV),
        "execution_state": _require_text(value, "execution_state"),
        "exit_code": _require_optional_int(value, "exit_code"),
        "started_at": _require_text(value, "started_at"),
        "completed_at": _require_text(value, "completed_at"),
        "duration_ms": _require_nonnegative_int(value, "duration_ms"),
        "stdout_summary": _require_string(value, "stdout_summary"),
        "stderr_summary": _require_string(value, "stderr_summary"),
        "output_capture": {
            "stdout": "bounded_summary",
            "stderr": "bounded_summary",
            "raw_output": "not_recorded",
            "stdout_truncated": _require_bool(output_capture, "stdout_truncated"),
            "stderr_truncated": _require_bool(output_capture, "stderr_truncated"),
        },
        "execution_observer": "scopecat_subprocess_executor",
    }


def _validate_probe_result_consistency(
    command_result: dict[str, Any],
    result_status: str,
    runtime_facts: dict[str, Any] | None,
    findings: tuple[UvRuntimeProbeFinding, ...],
) -> None:
    execution_state = command_result["execution_state"]
    if result_status != _runtime_probe_status_for_execution_state(execution_state):
        raise ValueError("uv runtime probe result_status must match execution_state")
    exit_code = command_result["exit_code"]
    if execution_state == "completed_success" and exit_code != 0:
        raise ValueError("completed uv runtime probe must have exit_code 0")
    if execution_state == "completed_failed" and (not isinstance(exit_code, int) or exit_code == 0):
        raise ValueError("failed uv runtime probe must have non-zero exit_code")
    if execution_state in {"timed_out", "launch_failed"} and exit_code is not None:
        raise ValueError("non-completed uv runtime probe must not have exit_code")

    expected_runtime_facts, parse_findings = _runtime_facts_from_stdout(
        command_result["stdout_summary"],
        execution_state,
        command_result["output_capture"]["stdout_truncated"],
    )
    if runtime_facts != expected_runtime_facts:
        raise ValueError("uv runtime probe runtime_facts must match command output")

    expected_findings = tuple(
        [
            *_runtime_probe_findings(execution_state),
            *parse_findings,
            *_runtime_fact_findings(runtime_facts),
        ]
    )
    if tuple(finding.to_dict() for finding in findings) != tuple(
        finding.to_dict() for finding in expected_findings
    ):
        raise ValueError("uv runtime probe findings must match execution_state and output")


def _validate_probe_result_request_alignment(
    probe_request_ref: dict[str, Any],
    command_result: dict[str, Any],
) -> None:
    for key in (
        "probe_request_id",
        "approval_id",
        "sync_request_id",
        "sync_result_id",
        "working_directory",
    ):
        if probe_request_ref[key] != command_result[key]:
            raise ValueError(f"uv runtime probe result {key} must match request ref")
    if tuple(probe_request_ref["command_intent"]["argv"]) != tuple(command_result["argv"]):
        raise ValueError("uv runtime probe result argv must match request ref")


def _runtime_probe_findings(execution_state: str) -> list[UvRuntimeProbeFinding]:
    if execution_state == "completed_failed":
        return [
            UvRuntimeProbeFinding(
                code="uv_runtime_probe_process_failed",
                severity="review",
                basis="The Scopecat-run uv runtime probe exited with a non-zero status.",
                does_not_claim="runtime_available_or_environment_ready",
            )
        ]
    if execution_state == "timed_out":
        return [
            UvRuntimeProbeFinding(
                code="uv_runtime_probe_process_timed_out",
                severity="review",
                basis="The Scopecat-run uv runtime probe exceeded the approved timeout.",
                does_not_claim="runtime_available_or_environment_ready",
            )
        ]
    if execution_state == "launch_failed":
        return [
            UvRuntimeProbeFinding(
                code="uv_runtime_probe_process_launch_failed",
                severity="review",
                basis="The Scopecat uv runtime probe subprocess could not be launched.",
                does_not_claim="manager_available_or_runtime_available",
            )
        ]
    return []


def _runtime_fact_findings(
    runtime_facts: dict[str, Any] | None,
) -> list[UvRuntimeProbeFinding]:
    if runtime_facts is None:
        return []
    if not runtime_facts["is_virtual_environment"]:
        return [
            UvRuntimeProbeFinding(
                code="runtime_probe_not_virtual_environment",
                severity="review",
                basis="The probed Python reported matching sys.prefix and sys.base_prefix.",
                does_not_claim="project_virtual_environment_used",
            )
        ]
    return []


def _runtime_probe_status_for_execution_state(execution_state: str) -> str:
    try:
        return RUNTIME_PROBE_STATUS_BY_EXECUTION_STATE[execution_state]
    except KeyError as exc:
        raise ValueError("uv runtime probe execution_state must be recognized") from exc


def _validate_probe_findings(
    findings: tuple[UvRuntimeProbeFinding, ...],
) -> tuple[UvRuntimeProbeFinding, ...]:
    validated = tuple(findings)
    if not all(isinstance(finding, UvRuntimeProbeFinding) for finding in validated):
        raise ValueError("uv runtime probe findings must be UvRuntimeProbeFinding objects")
    return validated


def _validate_attention(
    attention: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    normalized = []
    for item in tuple(copy.deepcopy(item) for item in attention):
        if not isinstance(item, dict):
            raise ValueError("uv runtime probe attention entries must be objects")
        normalized.append(
            {
                "code": _require_text(item, "code"),
                "severity": _require_text(item, "severity"),
                "basis": _require_text(item, "basis"),
                "does_not_claim": _require_text(item, "does_not_claim"),
            }
        )
    return tuple(normalized)


def _require_string(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _require_optional_int(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer or null")
    return value


def _require_nonnegative_int(source: dict[str, Any], key: str) -> int:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a nonnegative integer")
    return value


def _runtime_probe_attention() -> list[dict[str, str]]:
    return [
        {
            "code": "runtime_probe_only",
            "severity": "review",
            "basis": "Scopecat launched a bounded Python fact probe through uv run.",
            "does_not_claim": "run_readiness_or_experiment_execution",
        },
        {
            "code": "uv_no_sync_probe",
            "severity": "review",
            "basis": "The probe uses uv run --locked --no-sync and does not repair the environment.",
            "does_not_claim": "environment_synchronized_by_probe",
        },
        {
            "code": "package_state_not_verified",
            "severity": "review",
            "basis": "The probe records interpreter facts only, not installed package state.",
            "does_not_claim": "verified_package_environment",
        },
    ]
