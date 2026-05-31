"""Write a reviewed legacy sidecar evidence append receipt.

This module consumes an approved reviewed-legacy-sidecar append intent and
writes one review-evidence receipt under an existing measurement record. It
does not import primary data, parse legacy payloads, verify previews, repair
references, write parameters, decide measurement validity, replace manifests,
or define GUI behavior.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    validate_public_identifier,
    validate_relative_path,
    validate_strict_child_path,
)
from implementation_candidates.filesystem_mutation import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
    reject_existing_paths,
    target_exists,
    write_new_file,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_reviewed_legacy_sidecar_append_intent",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "append_behavior": "write_review_evidence_receipt",
    "overwrite_behavior": "no_overwrite_new_receipt",
    "lock_behavior": "record_local_lock_guard",
    "checksum_algorithm": "sha256",
    "storage_mutation": "write_review_evidence_receipt",
    "record_write": "append_review_evidence_receipt",
    "manifest_update": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "crash_recovery": "not_defined",
}

_APPEND_INTENT_POLICY_EXPECTATIONS = {
    "intent_authority": "explicit_reviewed_legacy_sidecar_append_intent",
    "source_review_handling": "legacy_locator_observation_review_bundle_summary",
    "approval_required": "explicit_operator_approval",
    "append_target": "existing_measurement_record_review_evidence",
    "fact_posture": "review_debug_evidence",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_import": "not_performed",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
}

_WRITE_REQUEST_FIELDS = {
    "request_id",
    "receipt_id",
    "append_intent_request_id",
    "measurement_id",
    "record_dir",
    "manifest_path",
    "receipt_path",
    "lock_path",
    "destination",
}

_DESTINATION_FIELDS = {"path_kind", "collision_policy"}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["evidence_append_receipt_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("reviewed legacy evidence append receipt policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"reviewed legacy evidence append receipt policy {key} must be {expected}"
            )


def _validate_append_intent(summary: dict[str, Any]) -> None:
    policy = summary["append_intent_policy"]
    for key, expected in _APPEND_INTENT_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"append intent policy {key} must be {expected}")
    intent = summary["append_intent"]
    if intent["approval_state"] != "approved":
        raise ValueError("evidence append receipt requires approved append intent")
    if (
        intent["append_destination"]["destination_kind"]
        != "existing_measurement_record_review_evidence"
    ):
        raise ValueError("append intent destination must target review evidence")
    if intent["append_destination"]["append_posture"] != "intent_only":
        raise ValueError("append intent must remain intent_only before receipt write")
    if intent["append_destination"]["record_write"] != "not_performed":
        raise ValueError("append intent must not already write records")
    for key in (
        "include_primary_data",
        "include_legacy_payloads",
        "include_reference_repair",
        "include_measurement_validity",
    ):
        if intent[key] is not False:
            raise ValueError(f"append intent {key} must be false")
    effects = summary["intent_effects"]
    for key in (
        "storage_mutation",
        "record_write",
        "primary_data_import",
        "data_observation",
        "row_count",
        "schema_inference",
        "preview_verification",
        "reference_repair",
        "parameter_write_back",
    ):
        if effects[key] != "not_performed":
            raise ValueError(f"append intent effect {key} must be not_performed")
    if effects["legacy_source_parsing"] != "not_performed_by_scopecat":
        raise ValueError("append intent must not parse legacy sources")
    if effects["measurement_validity"] != "not_claimed":
        raise ValueError("append intent must not claim measurement validity")


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(left.split("/"))
    right_parts = tuple(right.split("/"))
    return (
        left_parts == right_parts
        or left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
    )


def _validate_write_request(source: dict[str, Any]) -> None:
    request = source["write_request"]
    if set(request) != _WRITE_REQUEST_FIELDS:
        raise ValueError("reviewed legacy evidence append write request must match expected shape")
    for field in ("request_id", "receipt_id", "append_intent_request_id", "measurement_id"):
        validate_public_identifier(request[field], field)
    validate_relative_path(request["record_dir"], "write request record_dir")
    for field in ("manifest_path", "receipt_path", "lock_path"):
        validate_relative_path(request[field], f"write request {field}")
        validate_strict_child_path(request[field], request["record_dir"], f"write request {field}")
    if _paths_overlap(request["receipt_path"], request["lock_path"]):
        raise ValueError("receipt_path and lock_path must not overlap")
    destination = request["destination"]
    if set(destination) != _DESTINATION_FIELDS:
        raise ValueError("write request destination must match expected shape")
    if destination["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("write request destination path kind must stay relative")
    if destination["collision_policy"] != "no_overwrite_new_receipt":
        raise ValueError("write request collision policy must refuse overwrites")

    intent = source["reviewed_legacy_sidecar_append_intent_summary"]["append_intent"]
    if request["append_intent_request_id"] != intent["request_id"]:
        raise ValueError("write request append_intent_request_id must match append intent")
    if request["measurement_id"] != intent["measurement_id"]:
        raise ValueError("write request measurement_id must match append intent")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_append_intent(source["reviewed_legacy_sidecar_append_intent_summary"])
    _validate_write_request(source)


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _ensure_existing_record_dir(source: dict[str, Any], storage_root: Path) -> None:
    record_dir = source["write_request"]["record_dir"]
    ensure_no_symlink_parents(storage_root, record_dir, "reviewed legacy evidence record_dir")
    target = path_under(storage_root, record_dir)
    if target.is_symlink():
        raise ValueError("reviewed legacy evidence record directory is a symlink")
    if not target.is_dir():
        raise ValueError("reviewed legacy evidence record directory is unavailable")


def _read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight_existing_record(source: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    request = source["write_request"]
    _ensure_existing_record_dir(source, storage_root)
    ensure_no_symlink_parents(
        storage_root, request["manifest_path"], "reviewed legacy evidence manifest"
    )
    manifest_path = path_under(storage_root, request["manifest_path"])
    if manifest_path.is_symlink():
        raise ValueError("reviewed legacy evidence manifest target is a symlink")
    if not manifest_path.is_file():
        raise ValueError("reviewed legacy evidence manifest file is unavailable")
    manifest = _read_manifest(manifest_path)
    if manifest["measurement_record_id"] != request["measurement_id"]:
        raise ValueError("existing record manifest id must match write request")
    if manifest["record_dir"] != request["record_dir"]:
        raise ValueError("existing record manifest record_dir must match write request")
    return {
        "record_dir": request["record_dir"],
        "manifest_path": request["manifest_path"],
        "measurement_record_id": manifest["measurement_record_id"],
        "manifest_state": "matched_existing_record",
    }


def _receipt_payload(source: dict[str, Any]) -> dict[str, Any]:
    request = source["write_request"]
    intent_summary = source["reviewed_legacy_sidecar_append_intent_summary"]
    intent = intent_summary["append_intent"]
    return {
        "receipt_id": request["receipt_id"],
        "write_request_id": request["request_id"],
        "measurement_id": request["measurement_id"],
        "append_intent_request_id": request["append_intent_request_id"],
        "approved_at": intent["approved_at"],
        "operator_role": intent["operator_role"],
        "source_review": copy.deepcopy(intent_summary["source_review"]),
        "planned_review_evidence": copy.deepcopy(intent_summary["planned_review_evidence"]),
        "review_finding_count": len(intent_summary["review_findings"]),
        "review_findings": copy.deepcopy(intent_summary["review_findings"]),
        "receipt_effects": {
            "manifest_update": "not_performed",
            "primary_data_import": "not_performed",
            "legacy_payload_import": "not_performed",
            "legacy_source_parsing": "not_performed_by_scopecat",
            "preview_verification": "not_performed",
            "reference_repair": "not_performed",
            "parameter_write_back": "not_performed",
            "measurement_validity": "not_claimed",
        },
    }


def _receipt_bytes(source: dict[str, Any]) -> bytes:
    return json.dumps(_receipt_payload(source), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _lock_content(request: dict[str, Any]) -> bytes:
    return f"{request['request_id']}\n{request['receipt_id']}\n".encode("utf-8")


def _acquire_lock(storage_root: Path, request: dict[str, Any]) -> bytes:
    content = _lock_content(request)
    reject_existing_paths(
        storage_root,
        [request["lock_path"]],
        "reviewed legacy evidence append receipt lock",
    )
    write_new_file(
        storage_root,
        request["lock_path"],
        content,
        label="reviewed legacy evidence append receipt lock",
    )
    return content


def _release_owned_lock(storage_root: Path, lock_path: str, expected_content: bytes) -> None:
    try:
        lock = path_under(storage_root, lock_path)
        if lock.is_symlink() or not lock.is_file():
            return
        if lock.read_bytes() == expected_content:
            lock.unlink()
    except FileNotFoundError:
        pass


def _write_receipt(source: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    request = source["write_request"]
    if target_exists(storage_root, request["receipt_path"]):
        raise ValueError("reviewed legacy evidence append receipt already exists")
    receipt_content = _receipt_bytes(source)
    write_new_file(
        storage_root,
        request["receipt_path"],
        receipt_content,
        label="reviewed legacy evidence append receipt",
    )
    return {
        "path": request["receipt_path"],
        "kind": "review_evidence_receipt",
        "result": "written",
        "bytes_written": len(receipt_content),
        "digest": _sha256_bytes(receipt_content),
        "does_not_claim": "primary_data_import_manifest_update_or_validity",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "review_evidence_receipt_written",
            "severity": "review",
            "basis": "The approved append intent wrote one review-evidence receipt under an existing record.",
            "does_not_claim": "final_storage_append_model",
        },
        {
            "code": "record_lock_used",
            "severity": "review",
            "basis": "A direct record-local lock guard is used for this fixture mutation.",
            "does_not_claim": "distributed_locking_lock_identity_or_full_crash_recovery",
        },
        {
            "code": "manifest_not_replaced",
            "severity": "review",
            "basis": "The existing manifest is preflighted but not updated or replaced.",
            "does_not_claim": "read_model_refresh_or_manifest_merge",
        },
        {
            "code": "primary_data_not_imported",
            "severity": "review",
            "basis": "The receipt records review/debug evidence only.",
            "does_not_claim": "legacy_payload_materialization_or_preview_validation",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "The receipt does not decide measurement validity.",
            "does_not_claim": "measurement_validity",
        },
    ]


def write_reviewed_legacy_sidecar_evidence_append_receipt(
    source: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    """Write one review-evidence receipt for an approved legacy sidecar intent."""
    _validate_references(source)
    storage_root_resolved = existing_directory_root(
        storage_root, "reviewed legacy evidence append receipt storage"
    )
    request = source["write_request"]
    _ensure_existing_record_dir(source, storage_root_resolved)
    lock_content = _acquire_lock(storage_root_resolved, request)
    try:
        current_record = _preflight_existing_record(source, storage_root_resolved)
        write_result = _write_receipt(source, storage_root_resolved)
    finally:
        _release_owned_lock(storage_root_resolved, request["lock_path"], lock_content)

    intent_summary = source["reviewed_legacy_sidecar_append_intent_summary"]
    return {
        "evidence_append_receipt_policy": copy.deepcopy(source["evidence_append_receipt_policy"]),
        "classification": "reviewed_legacy_sidecar_evidence_receipt_written",
        "source_intent": {
            "request_id": intent_summary["append_intent"]["request_id"],
            "measurement_id": intent_summary["append_intent"]["measurement_id"],
            "classification": intent_summary["classification"],
            "review_finding_count": len(intent_summary["review_findings"]),
        },
        "current_record": current_record,
        "write_request": {
            "request_id": request["request_id"],
            "receipt_id": request["receipt_id"],
            "append_intent_request_id": request["append_intent_request_id"],
            "measurement_id": request["measurement_id"],
            "record_dir": request["record_dir"],
            "receipt_path": request["receipt_path"],
            "collision_policy": request["destination"]["collision_policy"],
            "lock_path": request["lock_path"],
            "lock_result": "acquired_and_released",
        },
        "write_results": [write_result],
        "receipt_effects": _receipt_payload(source)["receipt_effects"],
        "attention": _attention(),
    }
