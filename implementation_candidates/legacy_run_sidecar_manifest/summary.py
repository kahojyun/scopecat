"""Structured summary builder for a legacy-run sidecar manifest.

This module validates declared sidecar facts around a legacy experiment run. It
is deliberately side-effect free: it does not execute notebooks, control
runners, read primary data, import legacy records, observe files, mutate
storage, write parameters, infer schemas, or define GUI behavior.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "sidecar_authority": "declared_legacy_runtime_boundary",
    "legacy_runtime_execution": "external_unchanged",
    "manifest_posture": "local_review_summary",
    "primary_data_observation": "not_performed",
    "context_payload_import": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "schema_inference": "not_performed",
    "gui_workflow": "not_defined",
    "shared_workflow_schema": "not_defined",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "measurement_intent",
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
}
_CONTEXT_INCLUDE_STATES = {"selected", "unavailable", "optional_not_selected"}
_PRIMARY_REFERENCE_STATES = {"declared_available", "unavailable"}
_PRIMARY_KINDS = {"primary_data"}
_PRIMARY_FORMATS = {"legacy_csv_table", "csv_table", "npz_shots"}
_LEGACY_LOCATOR_KINDS = {
    "legacy_record_id",
    "legacy_path",
    "legacy_uri",
    "session_record_pair",
    "operator_note",
    "other",
}
_LEGACY_LOCATOR_REFERENCE_STATES = {"declared_available", "unavailable"}
_EVIDENCE_KINDS = {"attachment", "artifact", "debug_log", "opaque_snapshot"}
_EVIDENCE_LIFECYCLES = {"run_start", "during_run", "post_run"}
_EVIDENCE_REFERENCE_STATES = {"declared_available", "unavailable"}
_EVENT_TYPES = {
    "sidecar_manifest_started",
    "legacy_run_started",
    "legacy_dataset_declared",
    "sidecar_context_declared",
    "legacy_data_recorded",
    "legacy_run_completed",
    "legacy_run_stopped_partial",
    "legacy_run_failed",
}
_FINAL_EVENT_TYPES = {
    "legacy_run_completed",
    "legacy_run_stopped_partial",
    "legacy_run_failed",
}


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _display_is_public_safe(value: str) -> bool:
    lowered = value.lower()
    return (
        bool(value)
        and not value.startswith(("/", "~"))
        and "\\" not in value
        and not re.match(r"^[A-Za-z]:", value)
        and "/users/" not in lowered
        and "/private/" not in lowered
    )


def _parse_time(value: str, owner: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{owner} occurred_at must be ISO timestamp") from exc


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["sidecar_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy sidecar policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy sidecar policy {key} must be {expected}")


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_runtime(source: dict[str, Any]) -> None:
    runtime = source["legacy_runtime"]
    if runtime["execution_owner"] != "external_legacy_system":
        raise ValueError("legacy runtime execution_owner must stay external")
    if runtime["sidecar_mode"] != "observe_declared_boundary":
        raise ValueError("legacy runtime sidecar_mode is unsupported")
    if runtime["entrypoint"]["kind"] not in {"notebook", "python_function", "script"}:
        raise ValueError("legacy runtime entrypoint kind is unsupported")


def _validate_measurement(source: dict[str, Any]) -> None:
    measurement = source["measurement_record"]
    if not measurement["measurement_id"]:
        raise ValueError("measurement_id is required")
    if measurement["legacy_source_system_kind"] != "external_legacy_system":
        raise ValueError("legacy source system kind is unsupported")
    _validate_legacy_locators(
        measurement["legacy_source_locators"],
        "measurement legacy source",
        require_available=True,
    )


def _validate_legacy_locators(
    locators: list[dict[str, Any]],
    owner: str,
    *,
    require_available: bool,
) -> None:
    if not locators:
        if require_available:
            raise ValueError(f"{owner} requires at least one locator")
        return

    _records_by_key(locators, "locator_id")
    available_count = 0
    for locator in locators:
        if locator["kind"] not in _LEGACY_LOCATOR_KINDS:
            raise ValueError(f"{owner} locator kind is unsupported")
        if locator["reference_state"] not in _LEGACY_LOCATOR_REFERENCE_STATES:
            raise ValueError(f"{owner} locator reference_state is unsupported")
        if locator["reference_state"] == "declared_available":
            available_count += 1
            if locator.get("reason"):
                raise ValueError(f"{owner} available locator must not carry reason")
        elif not locator.get("reason"):
            raise ValueError(f"{owner} unavailable locator requires reason")
        if not _display_is_public_safe(locator["display"]):
            raise ValueError(f"{owner} locator display must be public-safe")
        if locator["kind"] == "legacy_path" and locator.get("redacted") is not True:
            raise ValueError(f"{owner} legacy_path locator must be redacted")

    if require_available and available_count == 0:
        raise ValueError(f"{owner} requires at least one available locator")


def _validate_context_refs(source: dict[str, Any]) -> None:
    seen = set()
    for ref in source["run_start_context_refs"]:
        ref_key = (ref["family"], ref["role"])
        if ref_key in seen:
            raise ValueError("duplicate context family role")
        seen.add(ref_key)
        if ref["family"] not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {ref['family']}")
        if ref["include_state"] not in _CONTEXT_INCLUDE_STATES:
            raise ValueError(f"unsupported context include_state: {ref['include_state']}")
        if ref["include_state"] == "selected":
            if not ref.get("context_id"):
                raise ValueError("selected context requires context_id")
            if not ref.get("authority"):
                raise ValueError("selected context requires authority")
            continue
        if ref.get("context_id"):
            raise ValueError("non-selected context must not carry context_id")
        if ref["required"] and not ref.get("missing_reason"):
            raise ValueError("required unavailable context needs missing_reason")


def _validate_primary_refs(source: dict[str, Any]) -> None:
    _records_by_key(source["primary_data_refs"], "data_id")
    for ref in source["primary_data_refs"]:
        if ref["kind"] not in _PRIMARY_KINDS:
            raise ValueError("primary data kind is unsupported")
        if ref["format"] not in _PRIMARY_FORMATS:
            raise ValueError("primary data format is unsupported")
        if ref["reference_state"] not in _PRIMARY_REFERENCE_STATES:
            raise ValueError("primary data reference_state is unsupported")
        if ref["reference_state"] == "declared_available":
            if ref.get("reason"):
                raise ValueError("available primary data must not carry reason")
            _validate_legacy_locators(
                ref["legacy_source_locators"],
                "primary data",
                require_available=True,
            )
        elif not ref.get("reason"):
            raise ValueError("unavailable primary data requires reason")
        else:
            _validate_legacy_locators(
                ref.get("legacy_source_locators", []),
                "primary data",
                require_available=False,
            )


def _validate_evidence_refs(source: dict[str, Any]) -> None:
    _records_by_key(source["supporting_evidence_refs"], "evidence_id")
    measurement_id = source["measurement_record"]["measurement_id"]
    for ref in source["supporting_evidence_refs"]:
        if ref["evidence_kind"] not in _EVIDENCE_KINDS:
            raise ValueError("supporting evidence kind is unsupported")
        if ref["lifecycle_stage"] not in _EVIDENCE_LIFECYCLES:
            raise ValueError("supporting evidence lifecycle_stage is unsupported")
        if ref["target"]["target_type"] != "measurement":
            raise ValueError("supporting evidence target_type must be measurement")
        if ref["target"]["target_id"] != measurement_id:
            raise ValueError("supporting evidence must target this measurement")
        if ref["reference_state"] not in _EVIDENCE_REFERENCE_STATES:
            raise ValueError("supporting evidence reference_state is unsupported")
        if ref["reference_state"] == "declared_available":
            _validate_relative_path(ref["declared_reference"]["path"], "supporting evidence")
            if ref.get("reason"):
                raise ValueError("available supporting evidence must not carry reason")
        elif not ref.get("reason"):
            raise ValueError("unavailable supporting evidence requires reason")


def _validate_events(source: dict[str, Any]) -> None:
    events = source["sidecar_events"]
    if len(events) < 3:
        raise ValueError("sidecar events require start, data, and final events")
    _records_by_key(events, "event_id")
    event_types = [event["event_type"] for event in events]
    unsupported = sorted(set(event_types) - _EVENT_TYPES)
    if unsupported:
        raise ValueError(f"unsupported sidecar event type: {unsupported[0]}")
    if event_types[0] != "sidecar_manifest_started":
        raise ValueError("first sidecar event must be sidecar_manifest_started")
    if event_types[-1] not in _FINAL_EVENT_TYPES:
        raise ValueError("last sidecar event must be final")
    if any(event_type in _FINAL_EVENT_TYPES for event_type in event_types[:-1]):
        raise ValueError("final sidecar event must be last")
    if "legacy_run_started" not in event_types:
        raise ValueError("sidecar events require legacy_run_started")
    if "legacy_data_recorded" not in event_types:
        raise ValueError("sidecar events require legacy_data_recorded")

    measurement_id = source["measurement_record"]["measurement_id"]
    previous_time: datetime | None = None
    previous_total = 0
    for event in events:
        occurred_at = _parse_time(event["occurred_at"], event["event_id"])
        if previous_time is not None and occurred_at < previous_time:
            raise ValueError("sidecar event timestamps must be monotonic")
        previous_time = occurred_at
        if event["measurement_id"] != measurement_id:
            raise ValueError("sidecar event measurement_id must match measurement record")
        if event["event_type"] == "legacy_data_recorded":
            points_recorded = event["points_recorded"]
            total_points_recorded = event["total_points_recorded"]
            if points_recorded <= 0:
                raise ValueError("legacy_data_recorded points_recorded must be positive")
            if total_points_recorded != previous_total + points_recorded:
                raise ValueError("legacy_data_recorded total must equal prior total plus points")
            previous_total = total_points_recorded

    final_event = events[-1]
    if final_event["final_recorded_points"] != previous_total:
        raise ValueError("final recorded points must match data-recorded total")
    if final_event["event_type"] == "legacy_run_failed" and not final_event.get("reason"):
        raise ValueError("failed legacy run requires reason")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_runtime(source)
    _validate_measurement(source)
    _validate_context_refs(source)
    _validate_primary_refs(source)
    _validate_evidence_refs(source)
    _validate_events(source)


def _lifecycle_summary(source: dict[str, Any]) -> dict[str, Any]:
    start_event = source["sidecar_events"][0]
    final_event = source["sidecar_events"][-1]
    state_by_event = {
        "legacy_run_completed": "completed",
        "legacy_run_stopped_partial": "partial",
        "legacy_run_failed": "failed",
    }
    return {
        "state": state_by_event[final_event["event_type"]],
        "started_at": start_event["occurred_at"],
        "ended_at": final_event["occurred_at"],
        "final_recorded_points": final_event["final_recorded_points"],
    }


def _classification(source: dict[str, Any]) -> str:
    final_event = source["sidecar_events"][-1]
    if final_event["event_type"] == "legacy_run_failed":
        return "legacy_sidecar_failed_run_needs_review"
    if final_event["event_type"] == "legacy_run_stopped_partial":
        return "legacy_sidecar_partial_run_needs_review"
    if any(
        ref["include_state"] != "selected" and ref["required"]
        for ref in source["run_start_context_refs"]
    ):
        return "legacy_sidecar_context_review_needed"
    if any(ref["reference_state"] != "declared_available" for ref in source["primary_data_refs"]):
        return "legacy_sidecar_primary_reference_review_needed"
    return "legacy_sidecar_ready_for_review"


def _context_counts(refs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "context_ref_count": len(refs),
        "selected_context_count": sum(1 for ref in refs if ref["include_state"] == "selected"),
        "required_context_count": sum(1 for ref in refs if ref["required"]),
        "unavailable_required_context_count": sum(
            1 for ref in refs if ref["required"] and ref["include_state"] != "selected"
        ),
    }


def _manifest_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for ref in source["run_start_context_refs"]:
        if ref["required"] and ref["include_state"] != "selected":
            findings.append(
                {
                    "code": "required_run_start_context_unavailable",
                    "severity": "review",
                    "family": ref["family"],
                    "role": ref["role"],
                    "basis": ref["missing_reason"],
                    "does_not_claim": "legacy_run_blocked_or_invalid",
                }
            )
    for ref in source["primary_data_refs"]:
        if ref["reference_state"] == "unavailable":
            findings.append(
                {
                    "code": "primary_data_reference_unavailable",
                    "severity": "review",
                    "data_id": ref["data_id"],
                    "basis": ref["reason"],
                    "does_not_claim": "primary_data_missing_from_legacy_system",
                }
            )
    final_event = source["sidecar_events"][-1]
    if final_event["event_type"] == "legacy_run_stopped_partial":
        findings.append(
            {
                "code": "legacy_run_partial",
                "severity": "review",
                "basis": final_event.get(
                    "reason", "Legacy run stopped before expected completion."
                ),
                "does_not_claim": "hardware_failure_or_measurement_invalid",
            }
        )
    if final_event["event_type"] == "legacy_run_failed":
        findings.append(
            {
                "code": "legacy_run_failed",
                "severity": "review",
                "basis": final_event["reason"],
                "does_not_claim": "retry_policy_or_root_cause",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "legacy_runtime_external",
            "severity": "info",
            "basis": "The sidecar records declared boundary facts while the legacy runtime executes outside Scopecat.",
            "does_not_claim": "runner_or_hardware_authority",
        },
        {
            "code": "manifest_not_storage_write",
            "severity": "review",
            "basis": "The sidecar manifest is a local review summary and does not create durable measurement storage.",
            "does_not_claim": "append_only_storage_record",
        },
        {
            "code": "primary_data_not_observed",
            "severity": "review",
            "basis": "Legacy primary-data references are carried as declarations without file observation or import.",
            "does_not_claim": "primary_data_opened_or_validated",
        },
        {
            "code": "context_payloads_not_imported",
            "severity": "review",
            "basis": "Run-start context references are optional links and their payloads are not imported.",
            "does_not_claim": "canonical_context_state",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "The sidecar does not apply calibration or parameter changes back to legacy files.",
            "does_not_claim": "parameter_state_updated",
        },
    ]
    if any(
        ref["include_state"] != "selected" and ref["required"]
        for ref in source["run_start_context_refs"]
    ):
        attention.append(
            {
                "code": "required_context_unavailable",
                "severity": "review",
                "basis": "At least one caller-required run-start context reference is unavailable.",
                "does_not_claim": "run_blocking_policy",
            }
        )
    return attention


def build_legacy_run_sidecar_manifest_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a local review summary from declared legacy-run sidecar facts."""
    _validate_references(source)
    return {
        "sidecar_policy": copy.deepcopy(source["sidecar_policy"]),
        "legacy_runtime": copy.deepcopy(source["legacy_runtime"]),
        "measurement_record": {
            **copy.deepcopy(source["measurement_record"]),
            "lifecycle": _lifecycle_summary(source),
            "classification": _classification(source),
        },
        "run_start_context": _context_counts(source["run_start_context_refs"]),
        "run_start_context_refs": copy.deepcopy(source["run_start_context_refs"]),
        "primary_data_refs": copy.deepcopy(source["primary_data_refs"]),
        "supporting_evidence_refs": copy.deepcopy(source["supporting_evidence_refs"]),
        "sidecar_events": copy.deepcopy(source["sidecar_events"]),
        "manifest_findings": _manifest_findings(source),
        "attention": _attention(source),
    }
