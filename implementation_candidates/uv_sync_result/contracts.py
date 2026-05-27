"""Candidate-local contracts for declared uv sync result records.

This slice records a declared result from an external ``uv sync`` run and
checks it against a prior bounded command intent. It does not execute
processes, read manifests or lockfiles, parse dependency output, inspect
runtimes, import code, execute selected code, probe hardware, or claim runnable
readiness.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

EXPECTED_POLICY = {
    "summary_policy": "review_summary",
    "result_authority": "declared_external_uv_sync_result",
    "prior_intent_source": "declared_uv_sync_intent_summary",
    "manager_scope": "uv_only",
    "command_result_shape": "bounded_uv_sync_result_record",
    "local_execution_cwd_authority": "declared_local_review_path_optional",
    "scopecat_process_execution": "not_performed",
    "manifest_read": "not_performed",
    "lockfile_read": "not_performed",
    "output_parsing": "summary_only_no_dependency_parsing",
    "dependency_resolution": "delegated_to_uv_not_performed_by_scopecat",
    "dependency_sync": "externally_reported_not_verified_by_scopecat",
    "package_install": "externally_reported_not_verified_by_scopecat",
    "runtime_probe": "not_performed",
    "code_import_execution": "not_performed",
    "hardware_probe": "not_performed",
    "readiness_claim": "not_claimed",
    "shared_environment_schema": "not_defined",
}

POLICY_ATTENTION_MATRIX = (
    {
        "policy_key": "summary_policy",
        "policy_value": "review_summary",
        "code": "uv_sync_result_record_only",
        "severity": "info",
        "basis": "The slice records a bounded external uv sync result for review.",
        "does_not_claim": "portable_public_report_or_run_readiness",
    },
    {
        "policy_key": "result_authority",
        "policy_value": "declared_external_uv_sync_result",
        "code": "external_result_is_declared",
        "severity": "review",
        "basis": "The result facts come from a declared external executor report.",
        "does_not_claim": "observed_or_executed_by_scopecat",
    },
    {
        "policy_key": "prior_intent_source",
        "policy_value": "declared_uv_sync_intent_summary",
        "code": "prior_intent_required",
        "severity": "review",
        "basis": "The result is checked against a declared prior uv sync command intent.",
        "does_not_claim": "standalone_unapproved_operation_result",
    },
    {
        "policy_key": "manager_scope",
        "policy_value": "uv_only",
        "code": "uv_manager_specific_result",
        "severity": "review",
        "basis": "The result shape is specific to uv sync and not a shared manager API.",
        "does_not_claim": "general_environment_manager_abstraction",
    },
    {
        "policy_key": "command_result_shape",
        "policy_value": "bounded_uv_sync_result_record",
        "code": "bounded_uv_sync_result_shape",
        "severity": "review",
        "basis": "The command result is a bounded uv-specific record, not raw process output.",
        "does_not_claim": "raw_execution_log_or_shared_result_schema",
    },
    {
        "policy_key": "local_execution_cwd_authority",
        "policy_value": "declared_local_review_path_optional",
        "code": "local_execution_cwd_is_review_fact",
        "severity": "review",
        "basis": (
            "The executor may report an absolute local cwd as review evidence; "
            "it is not used as the portable command cwd."
        ),
        "does_not_claim": "portable_public_path_reference",
    },
    {
        "policy_key": "scopecat_process_execution",
        "policy_value": "not_performed",
        "code": "scopecat_process_execution_not_performed",
        "severity": "review",
        "basis": "The slice accepts declared result facts and does not spawn subprocesses.",
        "does_not_claim": "command_executed_by_scopecat",
    },
    {
        "policy_key": "manifest_read",
        "policy_value": "not_performed",
        "code": "manifest_read_not_performed",
        "severity": "review",
        "basis": "The result record does not open pyproject.toml.",
        "does_not_claim": "manifest_parsed_or_dependency_groups_declared",
    },
    {
        "policy_key": "lockfile_read",
        "policy_value": "not_performed",
        "code": "lockfile_read_not_performed",
        "severity": "review",
        "basis": "The result record does not open or parse uv.lock.",
        "does_not_claim": "locked_dependency_graph",
    },
    {
        "policy_key": "output_parsing",
        "policy_value": "summary_only_no_dependency_parsing",
        "code": "output_parsing_summary_only",
        "severity": "review",
        "basis": "stdout and stderr are bounded review summaries, not parsed dependency facts.",
        "does_not_claim": "dependency_graph_or_package_change_set",
    },
    {
        "policy_key": "dependency_resolution",
        "policy_value": "delegated_to_uv_not_performed_by_scopecat",
        "code": "dependency_resolution_delegated_to_uv",
        "severity": "review",
        "basis": "Resolution semantics remain owned by uv.",
        "does_not_claim": "resolved_environment",
    },
    {
        "policy_key": "dependency_sync",
        "policy_value": "externally_reported_not_verified_by_scopecat",
        "code": "dependency_sync_externally_reported",
        "severity": "review",
        "basis": "The result records an external report and does not verify synchronized state.",
        "does_not_claim": "verified_synchronized_environment",
    },
    {
        "policy_key": "package_install",
        "policy_value": "externally_reported_not_verified_by_scopecat",
        "code": "package_install_externally_reported",
        "severity": "review",
        "basis": "The result does not inspect installed package state.",
        "does_not_claim": "verified_installed_environment",
    },
    {
        "policy_key": "runtime_probe",
        "policy_value": "not_performed",
        "code": "runtime_probe_not_performed",
        "severity": "review",
        "basis": "The result does not inspect interpreters, virtualenvs, or packages.",
        "does_not_claim": "runtime_available_or_compatible",
    },
    {
        "policy_key": "code_import_execution",
        "policy_value": "not_performed",
        "code": "code_execution_not_granted",
        "severity": "review",
        "basis": "The result does not import, load, or execute selected experiment code.",
        "does_not_claim": "execution_permission",
    },
    {
        "policy_key": "hardware_probe",
        "policy_value": "not_performed",
        "code": "hardware_probe_not_performed",
        "severity": "review",
        "basis": "The result does not contact instruments or control-PC hardware.",
        "does_not_claim": "control_pc_or_hardware_ready",
    },
    {
        "policy_key": "readiness_claim",
        "policy_value": "not_claimed",
        "code": "runnable_readiness_not_claimed",
        "severity": "review",
        "basis": "A uv sync result record does not decide whether a run can start.",
        "does_not_claim": "run_can_start",
    },
    {
        "policy_key": "shared_environment_schema",
        "policy_value": "not_defined",
        "code": "shared_environment_schema_not_defined",
        "severity": "review",
        "basis": "The slice validates candidate-local contracts only.",
        "does_not_claim": "shared_environment_schema",
    },
)

SOURCE_KEYS = {
    "uv_sync_result_policy",
    "uv_sync_intent_summary",
    "command_result",
}
INTENT_SUMMARY_REQUIRED_KEYS = {
    "intent_status",
    "sync_request",
    "command_intent",
}
INTENT_REQUEST_REQUIRED_KEYS = {
    "request_id",
    "approval_id",
    "working_directory",
    "expected_manager",
}
INTENT_COMMAND_REQUIRED_KEYS = {
    "manager",
    "operation",
    "working_directory",
    "argv",
    "does_not_claim",
}
COMMAND_RESULT_KEYS = {
    "result_id",
    "intent_request_id",
    "approval_id",
    "manager",
    "operation",
    "working_directory",
    "local_execution_cwd",
    "argv",
    "execution_state",
    "exit_code",
    "started_at",
    "completed_at",
    "duration_ms",
    "stdout_summary",
    "stderr_summary",
    "output_capture",
    "execution_observer",
}
OUTPUT_CAPTURE_KEYS = {
    "stdout",
    "stderr",
    "raw_output",
}

MANAGED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
ARGUMENT = re.compile(r"^-{0,2}[A-Za-z0-9][A-Za-z0-9_.:/=-]*$")
DEPENDENCY_GROUP = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
REVIEW_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._,:;()/+=@-]*$")
MANAGERS = {"uv"}
OPERATIONS = {"sync"}
INTENT_STATUSES = {"ready_for_external_review"}
INTENT_DOES_NOT_CLAIM = {"process_executed_or_environment_synchronized"}
EXECUTION_STATES = {"completed_success", "completed_failed", "not_run"}
EXECUTION_OBSERVERS = {"external_executor_declared"}
OUTPUT_CAPTURE_VALUES = {
    "stdout": "bounded_summary_only",
    "stderr": "bounded_summary_only",
    "raw_output": "not_recorded",
}


@dataclass(frozen=True)
class UvSyncResultPolicy:
    values: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "UvSyncResultPolicy":
        _require_shape(value, set(EXPECTED_POLICY), "uv sync result policy")
        for key, expected in EXPECTED_POLICY.items():
            if value[key] != expected:
                raise ValueError(f"uv sync result policy {key} must be {expected}")
        return cls(values=dict(value))

    def to_summary(self) -> dict[str, str]:
        return copy.deepcopy(self.values)


@dataclass(frozen=True)
class UvSyncIntentSummaryRef:
    request_id: str
    approval_id: str
    expected_manager: str
    working_directory: str
    command_manager: str
    operation: str
    argv: tuple[str, ...]
    does_not_claim: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "UvSyncIntentSummaryRef":
        _require_required_keys(value, INTENT_SUMMARY_REQUIRED_KEYS, "uv sync intent summary")
        intent_status = _required_str(value, "intent_status", "uv sync intent summary")
        if intent_status not in INTENT_STATUSES:
            raise ValueError("uv sync intent summary intent_status is unsupported")
        request = value["sync_request"]
        command = value["command_intent"]
        _require_required_keys(request, INTENT_REQUEST_REQUIRED_KEYS, "uv sync intent request")
        _require_required_keys(command, INTENT_COMMAND_REQUIRED_KEYS, "uv sync intent command")
        expected_manager = _required_str(request, "expected_manager", "uv sync intent request")
        command_manager = _required_str(command, "manager", "uv sync intent command")
        operation = _required_str(command, "operation", "uv sync intent command")
        request_working_directory = _required_str(
            request, "working_directory", "uv sync intent request"
        )
        command_working_directory = _required_str(
            command, "working_directory", "uv sync intent command"
        )
        does_not_claim = _required_str(command, "does_not_claim", "uv sync intent command")
        if expected_manager not in MANAGERS or command_manager not in MANAGERS:
            raise ValueError("uv sync result currently supports uv only")
        if expected_manager != command_manager:
            raise ValueError("uv sync intent expected_manager must match command manager")
        if operation not in OPERATIONS:
            raise ValueError("uv sync result currently supports sync only")
        if request_working_directory != command_working_directory:
            raise ValueError("uv sync intent working_directory fields must match")
        if not _directory_path_is_relative(request_working_directory):
            raise ValueError("uv sync intent working_directory must be relative")
        if does_not_claim not in INTENT_DOES_NOT_CLAIM:
            raise ValueError("uv sync intent command does_not_claim is unsupported")
        return cls(
            request_id=_required_managed_id(request, "request_id", "uv sync intent request"),
            approval_id=_required_managed_id(request, "approval_id", "uv sync intent request"),
            expected_manager=expected_manager,
            working_directory=request_working_directory,
            command_manager=command_manager,
            operation=operation,
            argv=tuple(_required_intent_argv(command["argv"])),
            does_not_claim=does_not_claim,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_id": self.approval_id,
            "expected_manager": self.expected_manager,
            "working_directory": self.working_directory,
            "command_intent": {
                "manager": self.command_manager,
                "operation": self.operation,
                "working_directory": self.working_directory,
                "argv": list(self.argv),
                "does_not_claim": self.does_not_claim,
            },
        }


@dataclass(frozen=True)
class CommandResult:
    result_id: str
    intent_request_id: str
    approval_id: str
    manager: str
    operation: str
    working_directory: str
    local_execution_cwd: str | None
    argv: tuple[str, ...]
    execution_state: str
    exit_code: int | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    stdout_summary: str
    stderr_summary: str
    output_capture: dict[str, str]
    execution_observer: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "CommandResult":
        _require_shape(value, COMMAND_RESULT_KEYS, "uv sync command result")
        manager = _required_str(value, "manager", "uv sync command result")
        operation = _required_str(value, "operation", "uv sync command result")
        execution_state = _required_str(value, "execution_state", "uv sync command result")
        execution_observer = _required_str(value, "execution_observer", "uv sync command result")
        output_capture = value["output_capture"]
        _require_shape(output_capture, OUTPUT_CAPTURE_KEYS, "uv sync output capture")
        for key, expected in OUTPUT_CAPTURE_VALUES.items():
            if output_capture[key] != expected:
                raise ValueError(f"uv sync output_capture {key} must be {expected}")
        if manager not in MANAGERS:
            raise ValueError("uv sync command result manager is unsupported")
        if operation not in OPERATIONS:
            raise ValueError("uv sync command result operation is unsupported")
        if execution_state not in EXECUTION_STATES:
            raise ValueError("uv sync command result execution_state is unsupported")
        if execution_observer not in EXECUTION_OBSERVERS:
            raise ValueError("uv sync command result execution_observer is unsupported")
        result = cls(
            result_id=_required_managed_id(value, "result_id", "uv sync command result"),
            intent_request_id=_required_managed_id(
                value, "intent_request_id", "uv sync command result"
            ),
            approval_id=_required_managed_id(value, "approval_id", "uv sync command result"),
            manager=manager,
            operation=operation,
            working_directory=_required_relative_directory(
                value, "working_directory", "uv sync command result"
            ),
            local_execution_cwd=_optional_local_path(
                value["local_execution_cwd"], "local_execution_cwd"
            ),
            argv=tuple(_required_argv(value["argv"], owner="uv sync command result")),
            execution_state=execution_state,
            exit_code=_optional_exit_code(value["exit_code"]),
            started_at=_optional_timestamp(value["started_at"], "started_at"),
            completed_at=_optional_timestamp(value["completed_at"], "completed_at"),
            duration_ms=_optional_duration(value["duration_ms"]),
            stdout_summary=_review_summary(value["stdout_summary"], "stdout_summary"),
            stderr_summary=_review_summary(value["stderr_summary"], "stderr_summary"),
            output_capture=dict(output_capture),
            execution_observer=execution_observer,
        )
        result._validate_execution_state()
        return result

    def _validate_execution_state(self) -> None:
        if self.execution_state == "not_run":
            if any(
                value is not None
                for value in (
                    self.exit_code,
                    self.started_at,
                    self.completed_at,
                    self.duration_ms,
                )
            ):
                raise ValueError("not_run uv sync result must not carry execution facts")
            if self.stdout_summary or self.stderr_summary:
                raise ValueError("not_run uv sync result must not carry output summaries")
            return
        if self.started_at is None or self.completed_at is None or self.duration_ms is None:
            raise ValueError("completed uv sync result requires timing facts")
        started_at = _timestamp_value(self.started_at)
        completed_at = _timestamp_value(self.completed_at)
        if completed_at < started_at:
            raise ValueError("completed uv sync result completed_at must not precede started_at")
        if self.duration_ms != _duration_ms_between(started_at, completed_at):
            raise ValueError("completed uv sync result duration_ms must match timestamps")
        if self.execution_state == "completed_success" and self.exit_code != 0:
            raise ValueError("completed_success uv sync result exit_code must be 0")
        if self.execution_state == "completed_failed":
            if self.exit_code is None or self.exit_code == 0:
                raise ValueError("completed_failed uv sync result exit_code must be non-zero")

    def to_summary(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "intent_request_id": self.intent_request_id,
            "approval_id": self.approval_id,
            "manager": self.manager,
            "operation": self.operation,
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
            "output_capture": copy.deepcopy(self.output_capture),
            "execution_observer": self.execution_observer,
        }


@dataclass(frozen=True)
class UvSyncResultContract:
    policy: UvSyncResultPolicy
    intent: UvSyncIntentSummaryRef
    result: CommandResult

    def validate(self) -> "UvSyncResultContract":
        if self.result.intent_request_id != self.intent.request_id:
            raise ValueError("uv sync result must reference intent request_id")
        if self.result.approval_id != self.intent.approval_id:
            raise ValueError("uv sync result must reference intent approval_id")
        return self


def validate_uv_sync_result_contract(source: dict[str, Any]) -> UvSyncResultContract:
    """Validate raw uv sync result input before projection."""
    _require_shape(source, SOURCE_KEYS, "uv sync result source")
    return UvSyncResultContract(
        policy=UvSyncResultPolicy.parse(source["uv_sync_result_policy"]),
        intent=UvSyncIntentSummaryRef.parse(source["uv_sync_intent_summary"]),
        result=CommandResult.parse(source["command_result"]),
    ).validate()


def _require_shape(value: Any, expected_keys: set[str], owner: str) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError(f"{owner} must match expected shape")


def _require_required_keys(value: Any, required_keys: set[str], owner: str) -> None:
    if not isinstance(value, dict) or not required_keys.issubset(value):
        raise ValueError(f"{owner} must include required keys")


def _required_str(value: dict[str, Any], key: str, owner: str) -> str:
    if key not in value:
        raise ValueError(f"{owner} must match expected shape")
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ValueError(f"{owner} {key} must be a non-empty string")
    return item


def _required_relative_directory(value: dict[str, Any], key: str, owner: str) -> str:
    item = _required_str(value, key, owner)
    if not _directory_path_is_relative(item):
        raise ValueError(f"{owner} {key} must be a relative command directory")
    return item


def _required_managed_id(value: dict[str, Any], key: str, owner: str) -> str:
    item = _required_str(value, key, owner)
    if not MANAGED_ID.fullmatch(item):
        raise ValueError(f"{owner} {key} must be a repository-safe managed identifier")
    return item


def _required_argv(value: Any, *, owner: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{owner} argv must be a non-empty list")
    args = []
    for arg in value:
        if not isinstance(arg, str) or not ARGUMENT.fullmatch(arg):
            raise ValueError(f"{owner} argv must contain bounded command arguments")
        args.append(arg)
    if args[:2] != ["uv", "sync"]:
        raise ValueError(f"{owner} argv must start with uv sync")
    return args


def _required_intent_argv(value: Any) -> list[str]:
    args = _required_argv(value, owner="uv sync intent command")
    if args[:4] != ["uv", "sync", "--locked", "--no-default-groups"]:
        raise ValueError("uv sync intent command argv must be bounded uv sync intent argv")
    group_args = args[4:]
    if len(group_args) % 2 != 0:
        raise ValueError("uv sync intent command argv must use --group pairs")
    for flag, group in zip(group_args[::2], group_args[1::2], strict=True):
        if flag != "--group" or not DEPENDENCY_GROUP.fullmatch(group):
            raise ValueError("uv sync intent command argv must use bounded dependency groups")
    return args


def _optional_exit_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 255:
        raise ValueError("uv sync command result exit_code must be 0..255 or null")
    return value


def _optional_duration(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("uv sync command result duration_ms must be non-negative or null")
    return value


def _optional_timestamp(value: Any, owner: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"uv sync command result {owner} must be an ISO UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"uv sync command result {owner} must be an ISO UTC timestamp") from exc
    return value


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _duration_ms_between(started_at: datetime, completed_at: datetime) -> int:
    delta = completed_at - started_at
    total_microseconds = (
        (delta.days * 24 * 60 * 60) + delta.seconds
    ) * 1_000_000 + delta.microseconds
    if total_microseconds % 1000 != 0:
        raise ValueError("completed uv sync result timestamps must align to milliseconds")
    return total_microseconds // 1000


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in parts)
    )


def _directory_path_is_relative(path: str) -> bool:
    return path == "." or _path_is_relative(path)


def _optional_local_path(value: Any, owner: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"uv sync command result {owner} must be a bounded local path")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"uv sync command result {owner} must not contain control text")
    return value


def _review_summary(value: Any, owner: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > 240 or not REVIEW_TEXT.fullmatch(value):
        raise ValueError(f"uv sync command result {owner} must be bounded review text")
    return value
