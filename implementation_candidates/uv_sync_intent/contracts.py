"""Candidate-local contracts for approved uv sync intent.

This slice validates a bounded ``uv sync`` command intent. It does not execute
the process, read manifests or lockfiles, resolve dependencies, install
packages, probe runtimes, import code, execute selected code, or define a
shared environment-manager abstraction.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

EXPECTED_POLICY = {
    "summary_policy": "review_summary",
    "operation_authority": "approved_uv_sync_intent",
    "manager_scope": "uv_only",
    "working_directory_authority": "declared_relative_workspace_path",
    "command_shape": "bounded_uv_sync_argv",
    "filesystem_inspection": "not_performed",
    "manifest_read": "not_performed",
    "lockfile_read": "not_performed",
    "dependency_resolution": "delegated_to_uv_not_performed_by_scopecat",
    "dependency_sync": "not_executed",
    "package_install": "not_performed_by_scopecat",
    "process_execution": "not_performed",
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
        "code": "uv_sync_intent_only",
        "severity": "info",
        "basis": "The slice validates a bounded uv sync command intent for review.",
        "does_not_claim": "environment_operation_executed",
    },
    {
        "policy_key": "manager_scope",
        "policy_value": "uv_only",
        "code": "uv_manager_specific_intent",
        "severity": "review",
        "basis": "The command shape is specific to uv and is not a shared manager API.",
        "does_not_claim": "general_environment_manager_abstraction",
    },
    {
        "policy_key": "filesystem_inspection",
        "policy_value": "not_performed",
        "code": "filesystem_inspection_not_performed",
        "severity": "review",
        "basis": "The intent validates declared path syntax but does not inspect the filesystem.",
        "does_not_claim": "workspace_or_manifest_exists",
    },
    {
        "policy_key": "manifest_read",
        "policy_value": "not_performed",
        "code": "manifest_read_not_performed",
        "severity": "review",
        "basis": "The intent does not open pyproject.toml before constructing argv.",
        "does_not_claim": "manifest_parsed_or_dependency_groups_declared",
    },
    {
        "policy_key": "lockfile_read",
        "policy_value": "not_performed",
        "code": "lockfile_read_not_performed",
        "severity": "review",
        "basis": "The intent may request uv --locked but does not open or parse uv.lock.",
        "does_not_claim": "locked_dependency_graph",
    },
    {
        "policy_key": "dependency_resolution",
        "policy_value": "delegated_to_uv_not_performed_by_scopecat",
        "code": "dependency_resolution_delegated_to_uv",
        "severity": "review",
        "basis": "Dependency resolution semantics remain owned by uv if the command is executed.",
        "does_not_claim": "resolved_environment",
    },
    {
        "policy_key": "dependency_sync",
        "policy_value": "not_executed",
        "code": "dependency_sync_not_executed",
        "severity": "review",
        "basis": "The slice returns argv only and does not run uv sync.",
        "does_not_claim": "synchronized_environment",
    },
    {
        "policy_key": "package_install",
        "policy_value": "not_performed_by_scopecat",
        "code": "package_install_not_performed",
        "severity": "review",
        "basis": "Any package installation would be an external uv effect after separate execution.",
        "does_not_claim": "installed_environment",
    },
    {
        "policy_key": "process_execution",
        "policy_value": "not_performed",
        "code": "process_execution_not_performed",
        "severity": "review",
        "basis": "The intent does not spawn subprocesses.",
        "does_not_claim": "external_command_completed",
    },
    {
        "policy_key": "runtime_probe",
        "policy_value": "not_performed",
        "code": "runtime_probe_not_performed",
        "severity": "review",
        "basis": "The intent does not inspect interpreters, virtualenvs, or installed packages.",
        "does_not_claim": "runtime_available_or_compatible",
    },
    {
        "policy_key": "code_import_execution",
        "policy_value": "not_performed",
        "code": "code_execution_not_granted",
        "severity": "review",
        "basis": "The intent does not import, load, or execute selected experiment code.",
        "does_not_claim": "execution_permission",
    },
    {
        "policy_key": "hardware_probe",
        "policy_value": "not_performed",
        "code": "hardware_probe_not_performed",
        "severity": "review",
        "basis": "The intent does not contact instruments, drivers, or control-PC hardware.",
        "does_not_claim": "control_pc_or_hardware_ready",
    },
    {
        "policy_key": "readiness_claim",
        "policy_value": "not_claimed",
        "code": "runnable_readiness_not_claimed",
        "severity": "review",
        "basis": "A command intent does not decide whether a run can start.",
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

EXPECTED_SCOPE_KEYS = {
    "managed_code_version_id",
    "editable_workspace_id",
    "prepared_run_context_id",
}
EXPECTED_ENVIRONMENT_CLAIMS = {
    "readiness_claim": "not_checked",
    "sync_claim": "not_synced",
    "execution_claim": "not_imported_loaded_or_executed",
    "hardware_claim": "not_probed",
}
EXPECTED_PREPARED_CONTEXT_CLAIM = "manual_run_context_only"
EXPECTED_APPROVED_OPERATION = "uv_sync_intent"
EXPECTED_SYNC_MODE = "include_project_dependencies_and_selected_groups"
EXPECTED_LOCK_POLICY = "uv_locked_mode"
EXPECTED_COMMAND_POLICY = "locked_no_default_groups"
EXPECTED_PROJECT_DEPENDENCIES = "declared"

ENVIRONMENT_AUTHORITIES = {
    "user_declared_inventory",
}
ENVIRONMENT_RECORD_STATUSES = {
    "declared",
}
MODERN_MANAGERS = {
    "uv",
}
MANIFEST_STATES = {
    "declared",
}
PYTHON_VERSION_SOURCES = {
    "requires-python",
}
SOURCE_KEYS = {
    "uv_sync_intent_policy",
    "sync_request",
    "prepared_run_context",
    "declared_environment",
}
SYNC_REQUEST_KEYS = {
    "request_id",
    "approval_id",
    "approved_operation",
    "workspace_root_label",
    "declared_environment_id",
    "prepared_run_context_id",
    "working_directory",
    "expected_manager",
    "include_project_dependencies",
    "dependency_groups",
    "sync_mode",
    "lock_policy",
    "command_policy",
}
PREPARED_RUN_CONTEXT_KEYS = {
    "prepared_run_context_id",
    "label",
    "scope",
    "selected_context_count",
    "preparation_claim",
}
DECLARED_ENVIRONMENT_KEYS = {
    "environment_id",
    "label",
    "authority",
    "record_status",
    "scope",
    "environment_claims",
    "modern_python_environment",
}
MODERN_PYTHON_ENVIRONMENT_KEYS = {
    "environment_ref",
    "manager",
    "pyproject_path",
    "lockfile_path",
    "project_dependencies",
    "dependency_groups",
    "python_version_source",
    "manifest_state",
}

MANAGED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
DEPENDENCY_GROUP = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
NORMALIZED_NAME_SEPARATOR = re.compile(r"[-_.]+")


def path_is_relative(path: str) -> bool:
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


def directory_path_is_relative(path: str) -> bool:
    return path == "." or path_is_relative(path)


def normalize_dependency_group(name: str) -> str:
    return NORMALIZED_NAME_SEPARATOR.sub("-", name).lower()


def _is_pyproject_path(path: str) -> bool:
    return PurePosixPath(path).name == "pyproject.toml"


def _is_uv_lock_path(path: str) -> bool:
    return PurePosixPath(path).name == "uv.lock"


@dataclass(frozen=True)
class Scope:
    managed_code_version_id: str
    editable_workspace_id: str
    prepared_run_context_id: str

    @classmethod
    def parse(cls, value: dict[str, Any], *, owner: str) -> "Scope":
        _require_shape(value, EXPECTED_SCOPE_KEYS, f"{owner} scope")
        return cls(
            managed_code_version_id=_required_managed_id(
                value, "managed_code_version_id", f"{owner} scope"
            ),
            editable_workspace_id=_required_managed_id(
                value, "editable_workspace_id", f"{owner} scope"
            ),
            prepared_run_context_id=_required_managed_id(
                value, "prepared_run_context_id", f"{owner} scope"
            ),
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "managed_code_version_id": self.managed_code_version_id,
            "editable_workspace_id": self.editable_workspace_id,
            "prepared_run_context_id": self.prepared_run_context_id,
        }


@dataclass(frozen=True)
class UvSyncIntentPolicy:
    values: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "UvSyncIntentPolicy":
        _require_shape(value, set(EXPECTED_POLICY), "uv sync intent policy")
        for key, expected in EXPECTED_POLICY.items():
            if value[key] != expected:
                raise ValueError(f"uv sync intent policy {key} must be {expected}")
        return cls(values=dict(value))

    def to_summary(self) -> dict[str, str]:
        return copy.deepcopy(self.values)


@dataclass(frozen=True)
class SyncRequest:
    request_id: str
    approval_id: str
    approved_operation: str
    workspace_root_label: str
    declared_environment_id: str
    prepared_run_context_id: str
    working_directory: str
    expected_manager: str
    include_project_dependencies: bool
    dependency_groups: tuple[str, ...]
    sync_mode: str
    lock_policy: str
    command_policy: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "SyncRequest":
        _require_shape(value, SYNC_REQUEST_KEYS, "uv sync request")
        approved_operation = _required_str(value, "approved_operation", "uv sync request")
        if approved_operation != EXPECTED_APPROVED_OPERATION:
            raise ValueError(
                f"uv sync request approved_operation must be {EXPECTED_APPROVED_OPERATION}"
            )
        workspace_root_label = _required_str(value, "workspace_root_label", "uv sync request")
        _validate_root_display_label(workspace_root_label)
        working_directory = _required_str(value, "working_directory", "uv sync request")
        if not directory_path_is_relative(working_directory):
            raise ValueError("uv sync request working_directory must be relative")
        expected_manager = _required_str(value, "expected_manager", "uv sync request")
        if expected_manager not in MODERN_MANAGERS:
            raise ValueError("uv sync intent currently supports uv")
        sync_mode = _required_str(value, "sync_mode", "uv sync request")
        if sync_mode != EXPECTED_SYNC_MODE:
            raise ValueError(f"uv sync request sync_mode must be {EXPECTED_SYNC_MODE}")
        lock_policy = _required_str(value, "lock_policy", "uv sync request")
        if lock_policy != EXPECTED_LOCK_POLICY:
            raise ValueError(f"uv sync request lock_policy must be {EXPECTED_LOCK_POLICY}")
        command_policy = _required_str(value, "command_policy", "uv sync request")
        if command_policy != EXPECTED_COMMAND_POLICY:
            raise ValueError(f"uv sync request command_policy must be {EXPECTED_COMMAND_POLICY}")
        include_project_dependencies = _required_bool(
            value, "include_project_dependencies", "uv sync request"
        )
        if not include_project_dependencies:
            raise ValueError("uv sync request must include project dependencies")
        groups = _group_list(value["dependency_groups"])
        return cls(
            request_id=_required_managed_id(value, "request_id", "uv sync request"),
            approval_id=_required_managed_id(value, "approval_id", "uv sync request"),
            approved_operation=approved_operation,
            workspace_root_label=workspace_root_label,
            declared_environment_id=_required_managed_id(
                value, "declared_environment_id", "uv sync request"
            ),
            prepared_run_context_id=_required_managed_id(
                value, "prepared_run_context_id", "uv sync request"
            ),
            working_directory=working_directory,
            expected_manager=expected_manager,
            include_project_dependencies=include_project_dependencies,
            dependency_groups=tuple(groups),
            sync_mode=sync_mode,
            lock_policy=lock_policy,
            command_policy=command_policy,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_id": self.approval_id,
            "approved_operation": self.approved_operation,
            "workspace_root_label": self.workspace_root_label,
            "declared_environment_id": self.declared_environment_id,
            "prepared_run_context_id": self.prepared_run_context_id,
            "working_directory": self.working_directory,
            "expected_manager": self.expected_manager,
            "include_project_dependencies": self.include_project_dependencies,
            "dependency_groups": list(self.dependency_groups),
            "sync_mode": self.sync_mode,
            "lock_policy": self.lock_policy,
            "command_policy": self.command_policy,
        }


@dataclass(frozen=True)
class PreparedRunContextRef:
    prepared_run_context_id: str
    label: str
    scope: Scope
    selected_context_count: int
    preparation_claim: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "PreparedRunContextRef":
        _require_shape(value, PREPARED_RUN_CONTEXT_KEYS, "prepared run context")
        if value["preparation_claim"] != EXPECTED_PREPARED_CONTEXT_CLAIM:
            raise ValueError("prepared run context claim must stay manual_run_context_only")
        return cls(
            prepared_run_context_id=_required_managed_id(
                value, "prepared_run_context_id", "prepared run context"
            ),
            label=_required_str(value, "label", "prepared run context"),
            scope=Scope.parse(value["scope"], owner="prepared run context"),
            selected_context_count=_required_non_negative_int(
                value, "selected_context_count", "prepared run context"
            ),
            preparation_claim=value["preparation_claim"],
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "prepared_run_context_id": self.prepared_run_context_id,
            "label": self.label,
            "scope": self.scope.to_summary(),
            "selected_context_count": self.selected_context_count,
            "preparation_claim": self.preparation_claim,
        }


@dataclass(frozen=True)
class ModernPythonEnvironmentRef:
    environment_ref: str
    manager: str
    pyproject_path: str
    lockfile_path: str
    project_dependencies: str
    dependency_groups: tuple[str, ...]
    python_version_source: str
    manifest_state: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "ModernPythonEnvironmentRef":
        _require_shape(value, MODERN_PYTHON_ENVIRONMENT_KEYS, "modern python environment")
        manager = _required_str(value, "manager", "modern python environment")
        if manager not in MODERN_MANAGERS:
            raise ValueError("uv sync intent currently supports uv")
        pyproject_path = _required_str(value, "pyproject_path", "modern python environment")
        lockfile_path = _required_str(value, "lockfile_path", "modern python environment")
        if not path_is_relative(pyproject_path):
            raise ValueError("modern python environment pyproject_path must be relative")
        if not path_is_relative(lockfile_path):
            raise ValueError("modern python environment lockfile_path must be relative")
        if not _is_pyproject_path(pyproject_path):
            raise ValueError("modern python environment pyproject_path must name pyproject.toml")
        if not _is_uv_lock_path(lockfile_path):
            raise ValueError("modern python environment lockfile_path must name uv.lock")
        if pyproject_path == lockfile_path:
            raise ValueError(
                "modern python environment pyproject_path must differ from lockfile_path"
            )
        if PurePosixPath(pyproject_path).parent != PurePosixPath(lockfile_path).parent:
            raise ValueError(
                "modern python environment pyproject_path and lockfile_path must share a parent"
            )
        project_dependencies = _required_str(
            value, "project_dependencies", "modern python environment"
        )
        if project_dependencies != EXPECTED_PROJECT_DEPENDENCIES:
            raise ValueError(
                f"modern python environment project_dependencies must be {EXPECTED_PROJECT_DEPENDENCIES}"
            )
        python_version_source = _required_str(
            value, "python_version_source", "modern python environment"
        )
        if python_version_source not in PYTHON_VERSION_SOURCES:
            raise ValueError("modern python environment python_version_source is unsupported")
        manifest_state = _required_str(value, "manifest_state", "modern python environment")
        if manifest_state not in MANIFEST_STATES:
            raise ValueError("modern python environment manifest_state is unsupported")
        return cls(
            environment_ref=_required_managed_id(
                value, "environment_ref", "modern python environment"
            ),
            manager=manager,
            pyproject_path=pyproject_path,
            lockfile_path=lockfile_path,
            project_dependencies=project_dependencies,
            dependency_groups=tuple(_group_list(value["dependency_groups"])),
            python_version_source=python_version_source,
            manifest_state=manifest_state,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "environment_ref": self.environment_ref,
            "manager": self.manager,
            "pyproject_path": self.pyproject_path,
            "lockfile_path": self.lockfile_path,
            "project_dependencies": self.project_dependencies,
            "dependency_groups": list(self.dependency_groups),
            "python_version_source": self.python_version_source,
            "manifest_state": self.manifest_state,
        }


@dataclass(frozen=True)
class DeclaredEnvironmentRef:
    environment_id: str
    label: str
    authority: str
    record_status: str
    scope: Scope
    environment_claims: dict[str, str]
    modern_python_environment: ModernPythonEnvironmentRef

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "DeclaredEnvironmentRef":
        _require_shape(value, DECLARED_ENVIRONMENT_KEYS, "declared environment")
        authority = _required_str(value, "authority", "declared environment")
        if authority not in ENVIRONMENT_AUTHORITIES:
            raise ValueError("declared environment authority must stay declared-only")
        record_status = _required_str(value, "record_status", "declared environment")
        if record_status not in ENVIRONMENT_RECORD_STATUSES:
            raise ValueError("declared environment record_status must stay declaration-only")
        claims = value["environment_claims"]
        _require_shape(claims, set(EXPECTED_ENVIRONMENT_CLAIMS), "declared environment claims")
        for key, expected in EXPECTED_ENVIRONMENT_CLAIMS.items():
            if claims[key] != expected:
                raise ValueError(f"declared environment {key} must be {expected}")
        return cls(
            environment_id=_required_managed_id(value, "environment_id", "declared environment"),
            label=_required_str(value, "label", "declared environment"),
            authority=authority,
            record_status=record_status,
            scope=Scope.parse(value["scope"], owner="declared environment"),
            environment_claims=dict(claims),
            modern_python_environment=ModernPythonEnvironmentRef.parse(
                value["modern_python_environment"]
            ),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "label": self.label,
            "authority": self.authority,
            "record_status": self.record_status,
            "scope": self.scope.to_summary(),
            "environment_claims": copy.deepcopy(self.environment_claims),
            "modern_python_environment": self.modern_python_environment.to_summary(),
        }


@dataclass(frozen=True)
class UvSyncIntentContract:
    policy: UvSyncIntentPolicy
    request: SyncRequest
    prepared_context: PreparedRunContextRef
    declared_environment: DeclaredEnvironmentRef

    def validate(self) -> "UvSyncIntentContract":
        if self.request.prepared_run_context_id != self.prepared_context.prepared_run_context_id:
            raise ValueError("uv sync request must match prepared run context")
        if self.request.declared_environment_id != self.declared_environment.environment_id:
            raise ValueError("uv sync request must match declared environment")
        if self.prepared_context.scope != self.declared_environment.scope:
            raise ValueError("declared environment scope must match prepared run context")
        if (
            self.prepared_context.scope.prepared_run_context_id
            != self.prepared_context.prepared_run_context_id
        ):
            raise ValueError("prepared run context scope must reference itself")
        manifest = self.declared_environment.modern_python_environment
        if self.request.expected_manager != manifest.manager:
            raise ValueError("uv sync request must match declared manager")
        if self.request.working_directory != str(PurePosixPath(manifest.pyproject_path).parent):
            raise ValueError("uv sync request working_directory must contain declared pyproject")
        if _normalized_group_set(self.request.dependency_groups) != _normalized_group_set(
            manifest.dependency_groups
        ):
            raise ValueError("uv sync request dependency groups must match declared environment")
        return self


def validate_uv_sync_intent_contract(source: dict[str, Any]) -> UvSyncIntentContract:
    """Validate raw uv sync intent input before projection."""
    _require_shape(source, SOURCE_KEYS, "uv sync intent source")
    return UvSyncIntentContract(
        policy=UvSyncIntentPolicy.parse(source["uv_sync_intent_policy"]),
        request=SyncRequest.parse(source["sync_request"]),
        prepared_context=PreparedRunContextRef.parse(source["prepared_run_context"]),
        declared_environment=DeclaredEnvironmentRef.parse(source["declared_environment"]),
    ).validate()


def _require_shape(value: Any, expected_keys: set[str], owner: str) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError(f"{owner} must match expected shape")


def _required_str(value: dict[str, Any], key: str, owner: str) -> str:
    if key not in value:
        raise ValueError(f"{owner} must match expected shape")
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ValueError(f"{owner} {key} must be a non-empty string")
    return item


def _required_managed_id(value: dict[str, Any], key: str, owner: str) -> str:
    item = _required_str(value, key, owner)
    if not MANAGED_ID.fullmatch(item):
        raise ValueError(f"{owner} {key} must be a repository-safe managed identifier")
    return item


def _required_non_negative_int(value: dict[str, Any], key: str, owner: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ValueError(f"{owner} {key} must be a non-negative integer")
    return item


def _required_bool(value: dict[str, Any], key: str, owner: str) -> bool:
    if key not in value:
        raise ValueError(f"{owner} must match expected shape")
    item = value[key]
    if not isinstance(item, bool):
        raise ValueError(f"{owner} {key} must be a boolean")
    return item


def _group_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("dependency groups must be a list")
    groups = []
    normalized_groups = []
    for group in value:
        if not isinstance(group, str) or not DEPENDENCY_GROUP.fullmatch(group):
            raise ValueError("dependency groups must be non-empty safe strings")
        if group in groups:
            raise ValueError(f"duplicate dependency group: {group}")
        normalized_group = normalize_dependency_group(group)
        if normalized_group in normalized_groups:
            raise ValueError(f"duplicate normalized dependency group: {group}")
        groups.append(group)
        normalized_groups.append(normalized_group)
    return groups


def _normalized_group_set(groups: tuple[str, ...]) -> set[str]:
    return {normalize_dependency_group(group) for group in groups}


def _validate_root_display_label(value: str) -> None:
    if "/" in value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise ValueError("workspace_root_label must be a non-path display label")
