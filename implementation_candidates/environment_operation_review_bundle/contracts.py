"""Candidate-local contracts for environment operation review bundles.

The bundle composes prior review summaries for one environment operation. It
does not execute managers, inspect filesystems, read manifests or lockfiles,
parse dependency output, resolve dependencies, verify sync/install state, probe
runtimes or hardware, import code, execute code, or claim runnable readiness.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

EXPECTED_POLICY = {
    "summary_policy": "review_summary",
    "bundle_authority": "explicit_prior_environment_operation_summaries",
    "manifest_preflight_source": "declared_modern_manifest_preflight_summary",
    "sync_intent_source": "declared_uv_sync_intent_summary",
    "sync_result_source": "declared_uv_sync_result_summary",
    "manager_scope": "uv_only",
    "composition_authority": "review_projection_only",
    "filesystem_inspection": "not_performed",
    "manifest_read": "not_performed",
    "lockfile_read": "not_performed",
    "process_execution": "not_performed",
    "dependency_output_parsing": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "externally_reported_not_verified_by_scopecat",
    "package_install": "externally_reported_not_verified_by_scopecat",
    "runtime_probe": "not_performed",
    "code_import_execution": "not_performed",
    "hardware_probe": "not_performed",
    "run_blocking_decision": "not_made",
    "readiness_claim": "not_claimed",
    "shared_environment_schema": "not_defined",
}

POLICY_ATTENTION_MATRIX = (
    {
        "policy_key": "summary_policy",
        "policy_value": "review_summary",
        "code": "environment_operation_review_only",
        "severity": "info",
        "basis": "The bundle composes prior operation review summaries for local review.",
        "does_not_claim": "portable_public_report_or_run_readiness",
    },
    {
        "policy_key": "bundle_authority",
        "policy_value": "explicit_prior_environment_operation_summaries",
        "code": "prior_summaries_required",
        "severity": "review",
        "basis": "The bundle validates declared prior summaries rather than observing environment state.",
        "does_not_claim": "fresh_environment_observation",
    },
    {
        "policy_key": "manager_scope",
        "policy_value": "uv_only",
        "code": "uv_operation_review_specific",
        "severity": "review",
        "basis": "The first operation review bundle is specific to uv sync.",
        "does_not_claim": "general_environment_manager_abstraction",
    },
    {
        "policy_key": "composition_authority",
        "policy_value": "review_projection_only",
        "code": "composition_review_projection_only",
        "severity": "review",
        "basis": "The bundle projects selected prior facts and does not own child slice semantics.",
        "does_not_claim": "shared_environment_schema",
    },
    {
        "policy_key": "filesystem_inspection",
        "policy_value": "not_performed",
        "code": "filesystem_inspection_not_performed",
        "severity": "review",
        "basis": "The bundle does not inspect workspace files or paths.",
        "does_not_claim": "workspace_or_manifest_exists",
    },
    {
        "policy_key": "manifest_read",
        "policy_value": "not_performed",
        "code": "manifest_read_not_performed",
        "severity": "review",
        "basis": "Manifest facts come from the prior preflight summary.",
        "does_not_claim": "fresh_manifest_parse",
    },
    {
        "policy_key": "lockfile_read",
        "policy_value": "not_performed",
        "code": "lockfile_read_not_performed",
        "severity": "review",
        "basis": "The bundle does not read or parse lockfiles.",
        "does_not_claim": "locked_dependency_graph",
    },
    {
        "policy_key": "process_execution",
        "policy_value": "not_performed",
        "code": "process_execution_not_performed",
        "severity": "review",
        "basis": "The bundle does not spawn uv or any other subprocess.",
        "does_not_claim": "command_executed_by_scopecat",
    },
    {
        "policy_key": "dependency_output_parsing",
        "policy_value": "not_performed",
        "code": "dependency_output_parsing_not_performed",
        "severity": "review",
        "basis": "The bundle treats result output as bounded summaries, not dependency facts.",
        "does_not_claim": "dependency_graph_or_package_change_set",
    },
    {
        "policy_key": "dependency_resolution",
        "policy_value": "not_performed",
        "code": "dependency_resolution_not_performed",
        "severity": "review",
        "basis": "Prior manifest and command facts are not dependency resolution.",
        "does_not_claim": "resolved_environment",
    },
    {
        "policy_key": "dependency_sync",
        "policy_value": "externally_reported_not_verified_by_scopecat",
        "code": "dependency_sync_externally_reported",
        "severity": "review",
        "basis": "The bundle may carry an external uv result but does not verify synchronized state.",
        "does_not_claim": "verified_synchronized_environment",
    },
    {
        "policy_key": "package_install",
        "policy_value": "externally_reported_not_verified_by_scopecat",
        "code": "package_install_externally_reported",
        "severity": "review",
        "basis": "The bundle does not inspect installed package state.",
        "does_not_claim": "verified_installed_environment",
    },
    {
        "policy_key": "runtime_probe",
        "policy_value": "not_performed",
        "code": "runtime_probe_not_performed",
        "severity": "review",
        "basis": "The bundle does not inspect interpreters, virtualenvs, or packages.",
        "does_not_claim": "runtime_available_or_compatible",
    },
    {
        "policy_key": "code_import_execution",
        "policy_value": "not_performed",
        "code": "code_execution_not_granted",
        "severity": "review",
        "basis": "The bundle does not import, load, or execute selected code.",
        "does_not_claim": "execution_permission",
    },
    {
        "policy_key": "hardware_probe",
        "policy_value": "not_performed",
        "code": "hardware_probe_not_performed",
        "severity": "review",
        "basis": "The bundle does not contact instruments or control-PC hardware.",
        "does_not_claim": "control_pc_or_hardware_ready",
    },
    {
        "policy_key": "run_blocking_decision",
        "policy_value": "not_made",
        "code": "run_blocking_decision_not_made",
        "severity": "review",
        "basis": "Review findings are not automatic run blocks.",
        "does_not_claim": "run_is_blocked_or_allowed",
    },
    {
        "policy_key": "readiness_claim",
        "policy_value": "not_claimed",
        "code": "runnable_readiness_not_claimed",
        "severity": "review",
        "basis": "The bundle does not decide whether a run can start.",
        "does_not_claim": "run_can_start",
    },
    {
        "policy_key": "shared_environment_schema",
        "policy_value": "not_defined",
        "code": "shared_environment_schema_not_defined",
        "severity": "review",
        "basis": "The bundle validates a candidate-local composition contract.",
        "does_not_claim": "shared_environment_schema",
    },
)

SOURCE_KEYS = {
    "environment_operation_review_policy",
    "operation_review_request",
    "modern_manifest_preflight_summary",
    "uv_sync_intent_summary",
    "uv_sync_result_summary",
}
REQUEST_KEYS = {
    "review_id",
    "prepared_run_context_id",
    "declared_environment_id",
    "expected_manager",
    "expected_operation",
    "manifest_preflight_request_id",
    "sync_intent_request_id",
    "sync_result_id",
}
MANIFEST_REQUIRED_KEYS = {
    "preflight_request",
    "preflight_status",
    "manifest_summary",
    "dependency_group_checks",
    "preflight_findings",
}
MANIFEST_REQUEST_REQUIRED_KEYS = {
    "request_id",
    "prepared_run_context_id",
    "declared_environment_id",
    "expected_manager",
}
INTENT_REQUIRED_KEYS = {
    "intent_status",
    "sync_request",
    "command_intent",
}
INTENT_REQUEST_REQUIRED_KEYS = {
    "request_id",
    "approval_id",
    "prepared_run_context_id",
    "declared_environment_id",
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
RESULT_REQUIRED_KEYS = {
    "uv_sync_intent_ref",
    "command_result",
    "result_status",
    "result_findings",
}
RESULT_INTENT_REF_REQUIRED_KEYS = {
    "request_id",
    "approval_id",
    "expected_manager",
    "working_directory",
    "command_intent",
}
RESULT_INTENT_COMMAND_REQUIRED_KEYS = {
    "manager",
    "operation",
    "working_directory",
    "argv",
    "does_not_claim",
}
COMMAND_RESULT_REQUIRED_KEYS = {
    "result_id",
    "intent_request_id",
    "approval_id",
    "manager",
    "operation",
    "working_directory",
    "argv",
    "execution_state",
    "exit_code",
}

MANAGED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
ARGUMENT = re.compile(r"^-{0,2}[A-Za-z0-9][A-Za-z0-9_.:/=-]*$")
DEPENDENCY_GROUP = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
MANAGERS = {"uv"}
OPERATIONS = {"sync"}
INTENT_STATUSES = {"ready_for_external_review"}
PREFLIGHT_STATUSES = {
    "manifest_preflight_passed_declared_checks",
    "manifest_preflight_has_review_findings",
}
PREFLIGHT_PASSING_STATUS = "manifest_preflight_passed_declared_checks"
RESULT_STATUSES = {
    "external_sync_reported_success",
    "external_sync_reported_failure",
    "external_sync_not_run",
    "result_requires_review",
}
EXECUTION_STATES = {"completed_success", "completed_failed", "not_run"}


@dataclass(frozen=True)
class EnvironmentOperationReviewPolicy:
    values: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentOperationReviewPolicy":
        _require_shape(value, set(EXPECTED_POLICY), "environment operation review policy")
        for key, expected in EXPECTED_POLICY.items():
            if value[key] != expected:
                raise ValueError(f"environment operation review policy {key} must be {expected}")
        return cls(values=dict(value))

    def to_summary(self) -> dict[str, str]:
        return copy.deepcopy(self.values)


@dataclass(frozen=True)
class OperationReviewRequest:
    review_id: str
    prepared_run_context_id: str
    declared_environment_id: str
    expected_manager: str
    expected_operation: str
    manifest_preflight_request_id: str
    sync_intent_request_id: str
    sync_result_id: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "OperationReviewRequest":
        _require_shape(value, REQUEST_KEYS, "operation review request")
        expected_manager = _required_str(value, "expected_manager", "operation review request")
        expected_operation = _required_str(value, "expected_operation", "operation review request")
        if expected_manager not in MANAGERS:
            raise ValueError("environment operation review currently supports uv only")
        if expected_operation not in OPERATIONS:
            raise ValueError("environment operation review currently supports sync only")
        return cls(
            review_id=_required_managed_id(value, "review_id", "operation review request"),
            prepared_run_context_id=_required_managed_id(
                value, "prepared_run_context_id", "operation review request"
            ),
            declared_environment_id=_required_managed_id(
                value, "declared_environment_id", "operation review request"
            ),
            expected_manager=expected_manager,
            expected_operation=expected_operation,
            manifest_preflight_request_id=_required_managed_id(
                value, "manifest_preflight_request_id", "operation review request"
            ),
            sync_intent_request_id=_required_managed_id(
                value, "sync_intent_request_id", "operation review request"
            ),
            sync_result_id=_required_managed_id(
                value, "sync_result_id", "operation review request"
            ),
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "review_id": self.review_id,
            "prepared_run_context_id": self.prepared_run_context_id,
            "declared_environment_id": self.declared_environment_id,
            "expected_manager": self.expected_manager,
            "expected_operation": self.expected_operation,
            "manifest_preflight_request_id": self.manifest_preflight_request_id,
            "sync_intent_request_id": self.sync_intent_request_id,
            "sync_result_id": self.sync_result_id,
        }


@dataclass(frozen=True)
class ManifestPreflightSummaryRef:
    request_id: str
    prepared_run_context_id: str
    declared_environment_id: str
    expected_manager: str
    preflight_status: str
    manifest_summary: dict[str, Any]
    dependency_group_checks: list[dict[str, Any]]
    preflight_findings: list[dict[str, Any]]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "ManifestPreflightSummaryRef":
        _require_required_keys(value, MANIFEST_REQUIRED_KEYS, "modern manifest preflight summary")
        request = value["preflight_request"]
        _require_required_keys(
            request, MANIFEST_REQUEST_REQUIRED_KEYS, "modern manifest preflight request"
        )
        expected_manager = _required_str(
            request, "expected_manager", "modern manifest preflight request"
        )
        if expected_manager not in MANAGERS:
            raise ValueError("environment operation review currently supports uv only")
        preflight_status = _required_str(
            value, "preflight_status", "modern manifest preflight summary"
        )
        if preflight_status not in PREFLIGHT_STATUSES:
            raise ValueError("modern manifest preflight summary preflight_status is unsupported")
        manifest_summary = _required_dict(
            value, "manifest_summary", "modern manifest preflight summary"
        )
        return cls(
            request_id=_required_managed_id(
                request, "request_id", "modern manifest preflight request"
            ),
            prepared_run_context_id=_required_managed_id(
                request, "prepared_run_context_id", "modern manifest preflight request"
            ),
            declared_environment_id=_required_managed_id(
                request, "declared_environment_id", "modern manifest preflight request"
            ),
            expected_manager=expected_manager,
            preflight_status=preflight_status,
            manifest_summary=copy.deepcopy(manifest_summary),
            dependency_group_checks=_required_dict_list(
                value, "dependency_group_checks", "modern manifest preflight summary"
            ),
            preflight_findings=_required_dict_list(
                value, "preflight_findings", "modern manifest preflight summary"
            ),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "prepared_run_context_id": self.prepared_run_context_id,
            "declared_environment_id": self.declared_environment_id,
            "expected_manager": self.expected_manager,
            "preflight_status": self.preflight_status,
            "manifest_summary": copy.deepcopy(self.manifest_summary),
            "dependency_group_checks": copy.deepcopy(self.dependency_group_checks),
            "preflight_findings": copy.deepcopy(self.preflight_findings),
        }


@dataclass(frozen=True)
class UvSyncIntentSummaryRef:
    request_id: str
    approval_id: str
    prepared_run_context_id: str
    declared_environment_id: str
    expected_manager: str
    working_directory: str
    manager: str
    operation: str
    argv: tuple[str, ...]
    does_not_claim: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "UvSyncIntentSummaryRef":
        _require_required_keys(value, INTENT_REQUIRED_KEYS, "uv sync intent summary")
        intent_status = _required_str(value, "intent_status", "uv sync intent summary")
        if intent_status not in INTENT_STATUSES:
            raise ValueError("uv sync intent summary intent_status is unsupported")
        request = value["sync_request"]
        command = value["command_intent"]
        _require_required_keys(request, INTENT_REQUEST_REQUIRED_KEYS, "uv sync intent request")
        _require_required_keys(command, INTENT_COMMAND_REQUIRED_KEYS, "uv sync intent command")
        expected_manager = _required_str(request, "expected_manager", "uv sync intent request")
        manager = _required_str(command, "manager", "uv sync intent command")
        operation = _required_str(command, "operation", "uv sync intent command")
        if expected_manager not in MANAGERS or manager not in MANAGERS:
            raise ValueError("environment operation review currently supports uv only")
        if operation not in OPERATIONS:
            raise ValueError("environment operation review currently supports sync only")
        working_directory = _required_relative_directory(
            request, "working_directory", "uv sync intent request"
        )
        command_working_directory = _required_str(
            command, "working_directory", "uv sync intent command"
        )
        if working_directory != command_working_directory:
            raise ValueError("uv sync intent working_directory fields must match")
        return cls(
            request_id=_required_managed_id(request, "request_id", "uv sync intent request"),
            approval_id=_required_managed_id(request, "approval_id", "uv sync intent request"),
            prepared_run_context_id=_required_managed_id(
                request, "prepared_run_context_id", "uv sync intent request"
            ),
            declared_environment_id=_required_managed_id(
                request, "declared_environment_id", "uv sync intent request"
            ),
            expected_manager=expected_manager,
            working_directory=working_directory,
            manager=manager,
            operation=operation,
            argv=tuple(_required_intent_argv(command["argv"], owner="uv sync intent command")),
            does_not_claim=_required_str(command, "does_not_claim", "uv sync intent command"),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_id": self.approval_id,
            "prepared_run_context_id": self.prepared_run_context_id,
            "declared_environment_id": self.declared_environment_id,
            "expected_manager": self.expected_manager,
            "working_directory": self.working_directory,
            "command_intent": {
                "manager": self.manager,
                "operation": self.operation,
                "working_directory": self.working_directory,
                "argv": list(self.argv),
                "does_not_claim": self.does_not_claim,
            },
        }


@dataclass(frozen=True)
class UvSyncResultSummaryRef:
    result_id: str
    intent_request_id: str
    approval_id: str
    result_intent_request_id: str
    result_intent_approval_id: str
    expected_manager: str
    result_intent_manager: str
    result_intent_operation: str
    result_intent_working_directory: str
    result_intent_argv: tuple[str, ...]
    result_intent_does_not_claim: str
    manager: str
    operation: str
    working_directory: str
    argv: tuple[str, ...]
    execution_state: str
    exit_code: int | None
    result_status: str
    result_findings: list[dict[str, Any]]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "UvSyncResultSummaryRef":
        _require_required_keys(value, RESULT_REQUIRED_KEYS, "uv sync result summary")
        intent_ref = value["uv_sync_intent_ref"]
        command_result = value["command_result"]
        _require_required_keys(
            intent_ref, RESULT_INTENT_REF_REQUIRED_KEYS, "uv sync result intent ref"
        )
        _require_required_keys(
            command_result, COMMAND_RESULT_REQUIRED_KEYS, "uv sync command result"
        )
        result_intent_command = intent_ref["command_intent"]
        _require_required_keys(
            result_intent_command,
            RESULT_INTENT_COMMAND_REQUIRED_KEYS,
            "uv sync result intent command",
        )
        expected_manager = _required_str(
            intent_ref, "expected_manager", "uv sync result intent ref"
        )
        result_intent_manager = _required_str(
            result_intent_command, "manager", "uv sync result intent command"
        )
        result_intent_operation = _required_str(
            result_intent_command, "operation", "uv sync result intent command"
        )
        result_intent_working_directory = _required_relative_directory(
            intent_ref, "working_directory", "uv sync result intent ref"
        )
        result_intent_command_working_directory = _required_str(
            result_intent_command, "working_directory", "uv sync result intent command"
        )
        manager = _required_str(command_result, "manager", "uv sync command result")
        operation = _required_str(command_result, "operation", "uv sync command result")
        result_status = _required_str(value, "result_status", "uv sync result summary")
        execution_state = _required_str(command_result, "execution_state", "uv sync command result")
        exit_code = _optional_exit_code(command_result["exit_code"])
        if (
            expected_manager not in MANAGERS
            or result_intent_manager not in MANAGERS
            or manager not in MANAGERS
        ):
            raise ValueError("environment operation review currently supports uv only")
        if result_intent_operation not in OPERATIONS or operation not in OPERATIONS:
            raise ValueError("environment operation review currently supports sync only")
        if result_intent_working_directory != result_intent_command_working_directory:
            raise ValueError("uv sync result intent working_directory fields must match")
        if result_status not in RESULT_STATUSES:
            raise ValueError("uv sync result summary result_status is unsupported")
        if execution_state not in EXECUTION_STATES:
            raise ValueError("uv sync command result execution_state is unsupported")
        _validate_result_state(result_status, execution_state, exit_code)
        return cls(
            result_id=_required_managed_id(command_result, "result_id", "uv sync command result"),
            intent_request_id=_required_managed_id(
                command_result, "intent_request_id", "uv sync command result"
            ),
            approval_id=_required_managed_id(
                command_result, "approval_id", "uv sync command result"
            ),
            result_intent_request_id=_required_managed_id(
                intent_ref, "request_id", "uv sync result intent ref"
            ),
            result_intent_approval_id=_required_managed_id(
                intent_ref, "approval_id", "uv sync result intent ref"
            ),
            expected_manager=expected_manager,
            result_intent_manager=result_intent_manager,
            result_intent_operation=result_intent_operation,
            result_intent_working_directory=result_intent_working_directory,
            result_intent_argv=tuple(
                _required_intent_argv(
                    result_intent_command["argv"], owner="uv sync result intent command"
                )
            ),
            result_intent_does_not_claim=_required_str(
                result_intent_command, "does_not_claim", "uv sync result intent command"
            ),
            manager=manager,
            operation=operation,
            working_directory=_required_relative_directory(
                command_result, "working_directory", "uv sync command result"
            ),
            argv=tuple(_required_argv(command_result["argv"], owner="uv sync command result")),
            execution_state=execution_state,
            exit_code=exit_code,
            result_status=result_status,
            result_findings=_required_dict_list(value, "result_findings", "uv sync result summary"),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "intent_request_id": self.intent_request_id,
            "approval_id": self.approval_id,
            "result_intent_ref": {
                "request_id": self.result_intent_request_id,
                "approval_id": self.result_intent_approval_id,
                "expected_manager": self.expected_manager,
                "working_directory": self.result_intent_working_directory,
                "command_intent": {
                    "manager": self.result_intent_manager,
                    "operation": self.result_intent_operation,
                    "working_directory": self.result_intent_working_directory,
                    "argv": list(self.result_intent_argv),
                    "does_not_claim": self.result_intent_does_not_claim,
                },
            },
            "expected_manager": self.expected_manager,
            "manager": self.manager,
            "operation": self.operation,
            "working_directory": self.working_directory,
            "argv": list(self.argv),
            "execution_state": self.execution_state,
            "exit_code": self.exit_code,
            "result_status": self.result_status,
            "result_findings": copy.deepcopy(self.result_findings),
        }


@dataclass(frozen=True)
class EnvironmentOperationReviewBundleContract:
    policy: EnvironmentOperationReviewPolicy
    request: OperationReviewRequest
    manifest: ManifestPreflightSummaryRef
    intent: UvSyncIntentSummaryRef
    result: UvSyncResultSummaryRef


def validate_environment_operation_review_bundle_contract(
    source: dict[str, Any],
) -> EnvironmentOperationReviewBundleContract:
    """Validate raw environment operation review input before projection."""
    _require_shape(source, SOURCE_KEYS, "environment operation review source")
    return EnvironmentOperationReviewBundleContract(
        policy=EnvironmentOperationReviewPolicy.parse(
            source["environment_operation_review_policy"]
        ),
        request=OperationReviewRequest.parse(source["operation_review_request"]),
        manifest=ManifestPreflightSummaryRef.parse(source["modern_manifest_preflight_summary"]),
        intent=UvSyncIntentSummaryRef.parse(source["uv_sync_intent_summary"]),
        result=UvSyncResultSummaryRef.parse(source["uv_sync_result_summary"]),
    )


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


def _required_dict(value: dict[str, Any], key: str, owner: str) -> dict[str, Any]:
    if key not in value or not isinstance(value[key], dict):
        raise ValueError(f"{owner} {key} must be an object")
    return value[key]


def _required_dict_list(value: dict[str, Any], key: str, owner: str) -> list[dict[str, Any]]:
    if key not in value or not isinstance(value[key], list):
        raise ValueError(f"{owner} {key} must be a list")
    items = []
    for item in value[key]:
        if not isinstance(item, dict):
            raise ValueError(f"{owner} {key} must contain objects")
        items.append(copy.deepcopy(item))
    return items


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


def _required_intent_argv(value: Any, *, owner: str) -> list[str]:
    args = _required_argv(value, owner=owner)
    if args[:4] != ["uv", "sync", "--locked", "--no-default-groups"]:
        raise ValueError(f"{owner} argv must be bounded uv sync intent argv")
    group_args = args[4:]
    if len(group_args) % 2 != 0:
        raise ValueError(f"{owner} argv must use --group pairs")
    for flag, group in zip(group_args[::2], group_args[1::2], strict=True):
        if flag != "--group" or not DEPENDENCY_GROUP.fullmatch(group):
            raise ValueError(f"{owner} argv must use bounded dependency groups")
    return args


def _optional_exit_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 255:
        raise ValueError("uv sync command result exit_code must be 0..255 or null")
    return value


def _validate_result_state(result_status: str, execution_state: str, exit_code: int | None) -> None:
    if execution_state == "completed_success" and exit_code != 0:
        raise ValueError("uv sync command result completed_success must have exit_code 0")
    if execution_state == "completed_failed" and exit_code in {None, 0}:
        raise ValueError("uv sync command result completed_failed must have non-zero exit_code")
    if execution_state == "not_run" and exit_code is not None:
        raise ValueError("uv sync command result not_run must have null exit_code")
    if result_status == "external_sync_reported_success":
        if execution_state != "completed_success" or exit_code != 0:
            raise ValueError("uv sync result success status must match execution facts")
    if result_status == "external_sync_reported_failure":
        if execution_state != "completed_failed" or exit_code in {None, 0}:
            raise ValueError("uv sync result failure status must match execution facts")
    if result_status == "external_sync_not_run":
        if execution_state != "not_run" or exit_code is not None:
            raise ValueError("uv sync result not-run status must match execution facts")


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
