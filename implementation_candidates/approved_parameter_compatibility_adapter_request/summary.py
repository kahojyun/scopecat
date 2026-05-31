"""Build an adapter input request for approved parameter compatibility output."""

from __future__ import annotations

import copy
import re
from typing import Any

_EXPECTED_POLICY = {
    "request_authority": "scopecat_approved_parameter_state",
    "approval_source": "prepared_run_operator_pre_run_approval_summary",
    "adapter_boundary": "user_authored_external_compatibility_adapter",
    "request_scope": "adapter_input_request_only",
    "adapter_execution": "not_performed",
    "compatibility_output": "not_produced",
    "file_write": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "durable_storage": "not_performed",
    "external_file_authority": "not_claimed",
    "gui_workflow": "not_defined",
    "managed_runner": "not_defined",
    "stable_public_adapter_api": "not_defined",
}

_ADAPTER_EXECUTION_AUTHORITY = "user_authored_external_adapter"
_TARGET_FORMATS = {"legacy_parameters_json", "project_specific_parameter_output"}
_VALUE_SHAPES = {"scalar"}
_PRIVATE_TOKEN_MARKERS = {"users", "private"}


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _validate_public_safe_token(value: str, owner: str, *, requires_redacted: bool) -> None:
    if (
        not value
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(marker in value.lower() for marker in _PRIVATE_TOKEN_MARKERS)
        or (requires_redacted and "redacted" not in value.lower())
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["adapter_request_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("approved parameter compatibility adapter request policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"adapter request policy {key} must be {expected}")


def _validate_approval_summary(source: dict[str, Any]) -> None:
    summary = source["operator_approval_summary"]
    if summary["classification"] != "operator_pre_run_review_approved":
        raise ValueError("adapter request requires approved operator pre-run review")
    effects = summary["decision_effects"]
    for key in (
        "automatic_run_start",
        "hardware_control",
        "parameter_write_back",
        "environment_operation",
        "code_import_execution",
        "durable_storage",
    ):
        if effects[key] != "not_performed":
            raise ValueError(f"operator approval effect {key} must be not_performed")
    if effects["run_start_claim"] != "not_claimed":
        raise ValueError("operator approval must not claim run start")
    if effects["compatibility_output"] != "not_produced":
        raise ValueError("operator approval must not produce compatibility output")


def _validate_adapter_profile(source: dict[str, Any]) -> None:
    profile = source["adapter_profile"]
    _validate_public_safe_token(profile["adapter_id"], "adapter_id", requires_redacted=False)
    _validate_public_safe_token(
        profile["target_profile_id"], "target_profile_id", requires_redacted=True
    )
    if profile["execution_authority"] != _ADAPTER_EXECUTION_AUTHORITY:
        raise ValueError("adapter execution authority must stay user-authored external adapter")
    if profile["target_format"] not in _TARGET_FORMATS:
        raise ValueError("adapter target format is unsupported")
    if profile["stable_public_api"] != "not_defined":
        raise ValueError("adapter profile must not define stable public API")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["adapter_request"]
    approval = source["operator_approval_summary"]
    review_request = approval["review_request"]
    if request["approval_id"] != approval["operator_decision"]["approval_id"]:
        raise ValueError("adapter request approval_id must match operator approval")
    if request["prepared_run_context_id"] != review_request["prepared_run_context_id"]:
        raise ValueError("adapter request prepared_run_context_id must match approval")
    if request["measurement_id"] != review_request["measurement_id"]:
        raise ValueError("adapter request measurement_id must match approval")
    if request["parameter_state_id"] != review_request["parameter_state_id"]:
        raise ValueError("adapter request parameter_state_id must match approval")
    if request["target_format"] != source["adapter_profile"]["target_format"]:
        raise ValueError("adapter request target_format must match adapter profile")
    target_hint = request["target_hint"]
    if target_hint["path_authority"] != "adapter_or_user_owned":
        raise ValueError("adapter request target path authority must remain adapter or user owned")
    if target_hint["scopecat_external_file_authority"] != "not_claimed":
        raise ValueError("adapter request must not claim external file authority")
    _validate_public_safe_token(
        target_hint["target_display_label"],
        "target_display_label",
        requires_redacted=True,
    )


def _validate_entries(source: dict[str, Any]) -> None:
    approval = source["operator_approval_summary"]
    selected = approval["selected_parameter_state"]
    entries = source["requested_entries"]
    if len(entries) != selected["trusted_entry_count"]:
        raise ValueError("adapter request entry count must match trusted entry count")
    paths = [entry["path"] for entry in entries]
    adapter_keys = [entry["adapter_key"] for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("adapter request entries contain duplicate path")
    if len(adapter_keys) != len(set(adapter_keys)):
        raise ValueError("adapter request entries contain duplicate adapter_key")
    for entry in entries:
        if entry["parameter_state_id"] != selected["state_id"]:
            raise ValueError("adapter request entry parameter_state_id must match selected state")
        if entry["trust_status"] != "trusted_for_declared_scope":
            raise ValueError("adapter request entry must be trusted for declared scope")
        if entry["value_shape"] not in _VALUE_SHAPES:
            raise ValueError("adapter request entry value shape is unsupported")
        if not _is_json_scalar(entry["value"]):
            raise ValueError("adapter request entry value must be scalar")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_approval_summary(source)
    _validate_adapter_profile(source)
    _validate_request(source)
    _validate_entries(source)


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": entry["path"],
        "adapter_key": entry["adapter_key"],
        "value": copy.deepcopy(entry["value"]),
        "unit": entry["unit"],
        "value_shape": entry["value_shape"],
        "request_state": "requested_for_external_adapter",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "adapter_request_only",
            "severity": "info",
            "basis": "Scopecat prepares reviewed parameter facts for a user-authored adapter.",
            "does_not_claim": "adapter_execution_or_output_written",
        },
        {
            "code": "external_format_owned_by_adapter",
            "severity": "review",
            "basis": "The external compatibility format is produced by user adapter code, not Scopecat core.",
            "does_not_claim": "stable_public_adapter_api_or_external_file_authority",
        },
        {
            "code": "hardware_and_write_back_not_performed",
            "severity": "review",
            "basis": "The adapter request does not apply parameters, control hardware, or emit compatibility output.",
            "does_not_claim": "hardware_safe_or_parameters_applied",
        },
    ]


def build_approved_parameter_compatibility_adapter_request_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a side-effect-free compatibility adapter request summary."""
    _validate_references(source)
    approval = source["operator_approval_summary"]
    request = source["adapter_request"]
    return {
        "adapter_request_policy": copy.deepcopy(source["adapter_request_policy"]),
        "classification": "compatibility_adapter_request_ready_for_external_adapter",
        "adapter_profile": copy.deepcopy(source["adapter_profile"]),
        "adapter_request": {
            "request_id": request["request_id"],
            "approval_id": request["approval_id"],
            "prepared_run_context_id": request["prepared_run_context_id"],
            "measurement_id": request["measurement_id"],
            "parameter_state_id": request["parameter_state_id"],
            "target_format": request["target_format"],
            "target_hint": copy.deepcopy(request["target_hint"]),
            "requested_by_role": request["requested_by_role"],
            "requested_at": request["requested_at"],
            "requested_entry_count": len(source["requested_entries"]),
        },
        "approval_context": {
            "classification": approval["classification"],
            "approval_id": approval["operator_decision"]["approval_id"],
            "operator_decision": approval["operator_decision"]["decision"],
            "review_gate_id": approval["review_request"]["review_gate_id"],
        },
        "prepared_run_context": copy.deepcopy(approval["prepared_run_context"]),
        "selected_parameter_state": copy.deepcopy(approval["selected_parameter_state"]),
        "requested_entries": [_entry_summary(entry) for entry in source["requested_entries"]],
        "request_effects": {
            "adapter_execution": "not_performed",
            "compatibility_output": "not_produced",
            "file_write": "not_performed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "external_file_authority": "not_claimed",
            "durable_storage": "not_performed",
        },
        "attention": _attention(),
    }
