"""Validate adapter-authored parameter compatibility output manifests."""

from __future__ import annotations

import copy
import re
from typing import Any

_MANIFEST_SCHEMA = "scopecat.adapter_parameter_compatibility_output_manifest.v0"

_EXPECTED_POLICY = {
    "manifest_authority": "adapter_authored",
    "request_source": "approved_parameter_compatibility_adapter_request_summary",
    "external_format_generation": "user_authored_adapter_declared",
    "scopecat_output_parsing": "not_performed",
    "adapter_execution_observation": "adapter_declared_only",
    "file_write": "not_performed_by_scopecat",
    "file_observation": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "external_file_authority": "not_claimed",
    "durable_storage": "not_performed",
    "gui_workflow": "not_defined",
    "managed_runner": "not_defined",
    "stable_public_adapter_api": "not_defined",
}

_OUTPUT_STATES = {"adapter_declared_produced", "adapter_declared_skipped"}
_ENTRY_STATES = {"adapter_declared_emitted", "adapter_declared_skipped"}
_FINDING_SEVERITIES = {"info", "review", "block_output"}
_PRIVATE_TOKEN_MARKERS = {"users", "private"}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_sha256_digest(value: str, owner: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{owner} digest must be sha256")


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


def _validate_request_summary(source: dict[str, Any]) -> None:
    request = source["adapter_request_summary"]
    if request["classification"] != "compatibility_adapter_request_ready_for_external_adapter":
        raise ValueError("compatibility output preview requires ready adapter request")
    effects = request["request_effects"]
    for key in (
        "adapter_execution",
        "file_write",
        "hardware_control",
        "parameter_write_back",
        "durable_storage",
    ):
        if effects[key] != "not_performed":
            raise ValueError(f"adapter request effect {key} must be not_performed")
    if effects["compatibility_output"] != "not_produced":
        raise ValueError("adapter request must not have produced compatibility output")
    if effects["external_file_authority"] != "not_claimed":
        raise ValueError("adapter request must not claim external file authority")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["adapter_output_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("adapter-authored compatibility output policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"adapter-authored compatibility output policy {key} must be {expected}"
            )


def _validate_manifest_identity(source: dict[str, Any]) -> None:
    if source["manifest_schema"] != _MANIFEST_SCHEMA:
        raise ValueError(f"manifest_schema must be {_MANIFEST_SCHEMA}")
    request_summary = source["adapter_request_summary"]
    manifest = source["adapter_output_manifest"]
    request = request_summary["adapter_request"]
    if manifest["request_id"] != request["request_id"]:
        raise ValueError("adapter output manifest request_id must match request")
    if manifest["approval_id"] != request["approval_id"]:
        raise ValueError("adapter output manifest approval_id must match request")
    if manifest["prepared_run_context_id"] != request["prepared_run_context_id"]:
        raise ValueError("adapter output manifest prepared_run_context_id must match request")
    if manifest["measurement_id"] != request["measurement_id"]:
        raise ValueError("adapter output manifest measurement_id must match request")
    if manifest["parameter_state_id"] != request["parameter_state_id"]:
        raise ValueError("adapter output manifest parameter_state_id must match request")
    if manifest["adapter_id"] != request_summary["adapter_profile"]["adapter_id"]:
        raise ValueError("adapter output manifest adapter_id must match request")
    if manifest["target_format"] != request["target_format"]:
        raise ValueError("adapter output manifest target_format must match request")
    if manifest["output_state"] not in _OUTPUT_STATES:
        raise ValueError("adapter output state is unsupported")


def _validate_target(source: dict[str, Any]) -> None:
    request_target = source["adapter_request_summary"]["adapter_request"]["target_hint"]
    target = source["adapter_output_manifest"]["target"]
    _validate_public_safe_token(
        target["target_display_label"], "target_display_label", requires_redacted=True
    )
    if target["target_display_label"] != request_target["target_display_label"]:
        raise ValueError("adapter output target display must match request target hint")
    if target["target_authority"] != "adapter_declared":
        raise ValueError("adapter output target authority must stay adapter_declared")
    if target["scopecat_external_file_authority"] != "not_claimed":
        raise ValueError("adapter output must not claim Scopecat external file authority")
    if target["reference_state"] not in {
        "adapter_declared_available",
        "adapter_declared_unavailable",
    }:
        raise ValueError("adapter output target reference_state is unsupported")
    if target["reference_state"] == "adapter_declared_available":
        if not target.get("digest"):
            raise ValueError("adapter output target requires digest when available")
        _validate_sha256_digest(target["digest"], "adapter output target")
        if not isinstance(target.get("size_bytes"), int) or target["size_bytes"] <= 0:
            raise ValueError("adapter output target size_bytes must be positive")
    elif not target.get("reason"):
        raise ValueError("adapter output target requires reason when unavailable")


def _validate_entries(source: dict[str, Any]) -> None:
    requested = _records_by_key(
        source["adapter_request_summary"]["requested_entries"], "adapter_key"
    )
    emitted = source["adapter_output_manifest"]["entries"]
    adapter_keys = [entry["adapter_key"] for entry in emitted]
    if len(adapter_keys) != len(set(adapter_keys)):
        raise ValueError("adapter output entries contain duplicate adapter_key")
    if set(adapter_keys) != set(requested):
        raise ValueError("adapter output entries must account for every requested adapter_key")
    for entry in emitted:
        requested_entry = requested[entry["adapter_key"]]
        if entry["entry_state"] not in _ENTRY_STATES:
            raise ValueError("adapter output entry_state is unsupported")
        if entry["path"] != requested_entry["path"]:
            raise ValueError("adapter output entry path must match request")
        if entry["entry_state"] == "adapter_declared_emitted":
            for key in ("value", "unit", "value_shape"):
                if entry[key] != requested_entry[key]:
                    raise ValueError(f"adapter output emitted entry {key} must match request")
        elif not entry.get("reason"):
            raise ValueError("adapter output skipped entry requires reason")


def _validate_adapter_findings(source: dict[str, Any]) -> None:
    seen = set()
    for finding in source["adapter_findings"]:
        code = finding["code"]
        if code in seen:
            raise ValueError(f"duplicate adapter finding code: {code}")
        seen.add(code)
        if finding["severity"] not in _FINDING_SEVERITIES:
            raise ValueError("adapter output finding severity is unsupported")
        if not finding["message"]:
            raise ValueError("adapter output finding requires message")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_request_summary(source)
    _validate_policy(source)
    _validate_manifest_identity(source)
    _validate_target(source)
    _validate_entries(source)
    _validate_adapter_findings(source)


def _classification(source: dict[str, Any]) -> str:
    manifest = source["adapter_output_manifest"]
    if any(finding["severity"] == "block_output" for finding in source["adapter_findings"]):
        return "adapter_compatibility_output_blocked_by_adapter_finding"
    if manifest["target"]["reference_state"] != "adapter_declared_available":
        return "adapter_compatibility_output_needs_target_review"
    if manifest["output_state"] != "adapter_declared_produced":
        return "adapter_compatibility_output_needs_review"
    if any(entry["entry_state"] != "adapter_declared_emitted" for entry in manifest["entries"]):
        return "adapter_compatibility_output_ready_with_findings"
    if source["adapter_findings"]:
        return "adapter_compatibility_output_ready_with_findings"
    return "adapter_compatibility_output_ready_for_review"


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    output = {
        "adapter_key": entry["adapter_key"],
        "path": entry["path"],
        "entry_state": entry["entry_state"],
    }
    for key in ("value", "unit", "value_shape", "reason"):
        if key in entry:
            output[key] = copy.deepcopy(entry[key])
    return output


def _target_summary(target: dict[str, Any]) -> dict[str, Any]:
    output = {
        "target_display_label": target["target_display_label"],
        "target_authority": target["target_authority"],
        "reference_state": target["reference_state"],
        "scopecat_external_file_authority": target["scopecat_external_file_authority"],
    }
    for key in ("digest", "size_bytes", "reason"):
        if key in target:
            output[key] = target[key]
    return output


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "adapter_authored_output_manifest",
            "severity": "info",
            "basis": "Scopecat validates adapter-declared output facts, not the lab-specific output payload.",
            "does_not_claim": "output_payload_parsed_by_scopecat",
        },
        {
            "code": "external_file_authority_not_claimed",
            "severity": "review",
            "basis": "The produced compatibility target remains adapter-declared external output.",
            "does_not_claim": "scopecat_managed_external_file_authority",
        },
        {
            "code": "hardware_and_write_back_not_performed",
            "severity": "review",
            "basis": "Previewing the adapter manifest does not apply parameters or control hardware.",
            "does_not_claim": "hardware_safe_or_parameters_applied",
        },
    ]


def build_adapter_authored_parameter_compatibility_output_preview_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a preview summary for an adapter-authored compatibility output manifest."""
    _validate_references(source)
    manifest = source["adapter_output_manifest"]
    return {
        "adapter_output_policy": copy.deepcopy(source["adapter_output_policy"]),
        "classification": _classification(source),
        "request_context": {
            "request_id": manifest["request_id"],
            "approval_id": manifest["approval_id"],
            "prepared_run_context_id": manifest["prepared_run_context_id"],
            "measurement_id": manifest["measurement_id"],
            "parameter_state_id": manifest["parameter_state_id"],
        },
        "adapter": {
            "adapter_id": manifest["adapter_id"],
            "target_format": manifest["target_format"],
            "output_state": manifest["output_state"],
        },
        "target": _target_summary(manifest["target"]),
        "entries": [_entry_summary(entry) for entry in manifest["entries"]],
        "adapter_findings": copy.deepcopy(source["adapter_findings"]),
        "preview_effects": {
            "scopecat_output_parsing": "not_performed",
            "file_write": "not_performed",
            "file_observation": "not_performed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "external_file_authority": "not_claimed",
            "durable_storage": "not_performed",
        },
        "attention": _attention(),
    }
