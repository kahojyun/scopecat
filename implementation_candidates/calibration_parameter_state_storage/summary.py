"""Storage writer for calibration-derived parameter-state intake.

This implementation candidate writes one reviewed calibration-derived
parameter-state summary under a caller-provided storage root. It follows the
same bounded no-overwrite filesystem pattern as the adapter storage writer,
but preserves calibration handoff provenance instead of forcing it into
adapter/legacy-source fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from implementation_candidates.calibration_parameter_state_intake import (
    build_calibration_parameter_state_intake_summary,
)
from implementation_candidates.contract_primitives import relative_path_parts
from implementation_candidates.filesystem_mutation import (
    existing_directory_root,
    reject_existing_paths,
    write_new_files_transaction,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_calibration_parameter_state_storage_write",
    "input_authority": "calibration_parameter_state_intake_summary",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "overwrite_behavior": "no_overwrite",
    "checksum_algorithm": "sha256",
    "calibration_payload_handling": "summary_only",
    "storage_mutation": "performed",
    "external_compatibility_output": "not_produced",
    "hardware_write_back": "not_performed",
    "rollback": "not_defined",
    "calibration_execution": "not_performed",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["storage_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected calibration parameter-state storage policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"calibration parameter-state storage policy {key} must be {expected}")


def _validate_storage_request(source: dict[str, Any]) -> None:
    request = source["storage_request"]
    if request["approval"]["approval_state"] != "approved":
        raise ValueError("calibration parameter-state storage write request must be approved")
    destination = request["destination"]
    if destination["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError(
            "calibration parameter-state storage destination path kind must be relative"
        )
    if destination["collision_policy"] != "no_overwrite":
        raise ValueError(
            "calibration parameter-state storage collision policy must refuse overwrites"
        )

    for field in ("state_dir", "manifest_path", "receipt_path"):
        relative_path_parts(request[field], f"storage request {field}")
    state_dir = request["state_dir"]
    for field in ("manifest_path", "receipt_path"):
        path = request[field]
        if not path.startswith(f"{state_dir}/"):
            raise ValueError(f"storage request {field} must stay under state_dir")
    if request["manifest_path"] == request["receipt_path"]:
        raise ValueError("calibration parameter-state manifest and receipt paths must differ")
    manifest_parts = relative_path_parts(request["manifest_path"], "manifest_path")
    receipt_parts = relative_path_parts(request["receipt_path"], "receipt_path")
    if (
        manifest_parts[: len(receipt_parts)] == receipt_parts
        or receipt_parts[: len(manifest_parts)] == manifest_parts
    ):
        raise ValueError("calibration parameter-state storage output paths must not overlap")


def _validate_intake_continuity(source: dict[str, Any], intake_summary: dict[str, Any]) -> None:
    request = source["storage_request"]
    state = intake_summary["managed_parameter_state"]
    if request["source_intake_review_id"] != intake_summary["intake_review"]["review_id"]:
        raise ValueError("storage request source_intake_review_id must match intake review")
    if request["source_handoff_id"] != intake_summary["source_handoff"]["handoff_id"]:
        raise ValueError("storage request source_handoff_id must match intake handoff")
    if request["state_id"] != state["state_id"]:
        raise ValueError("storage request state_id must match intake managed state")
    if state["source_handoff_id"] != intake_summary["source_handoff"]["handoff_id"]:
        raise ValueError("managed parameter state must reference source handoff")
    if state["created_by_review_id"] != intake_summary["intake_review"]["review_id"]:
        raise ValueError("managed parameter state must reference intake review")
    if intake_summary["review_findings"]:
        raise ValueError("storage requires calibration parameter-state intake without findings")


def _validate_side_effects(source: dict[str, Any]) -> None:
    side_effects = source["side_effect_claims"]
    if side_effects["storage_mutation"] != "performed":
        raise ValueError("side effect claim storage_mutation must be performed")
    for key in ("hardware_write_back", "calibration_execution"):
        if side_effects[key] != "not_performed":
            raise ValueError(f"side effect claim {key} must be not_performed")
    if side_effects["external_compatibility_output"] != "not_produced":
        raise ValueError("side effect claim external_compatibility_output must be not_produced")
    if side_effects["rollback"] != "not_defined":
        raise ValueError("side effect claim rollback must be not_defined")


def _validate_references(source: dict[str, Any], intake_summary: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_storage_request(source)
    _validate_intake_continuity(source, intake_summary)
    _validate_side_effects(source)


def _manifest_bytes(source: dict[str, Any], intake_summary: dict[str, Any]) -> bytes:
    manifest = {
        "manifest_schema": "scopecat.calibration_parameter_state_storage_manifest.v0",
        "state": copy.deepcopy(intake_summary["managed_parameter_state"]),
        "changed_entries": copy.deepcopy(intake_summary["changed_entries"]),
        "provenance": copy.deepcopy(intake_summary["provenance"]),
        "source_review": copy.deepcopy(intake_summary["intake_review"]),
        "source_handoff": copy.deepcopy(intake_summary["source_handoff"]),
        "storage_non_claims": {
            "external_compatibility_output": "not_produced",
            "hardware_write_back": "not_performed",
            "rollback": "not_defined",
            "calibration_execution": "not_performed",
            "shared_parameter_schema": "not_defined",
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _receipt_bytes(
    source: dict[str, Any],
    intake_summary: dict[str, Any],
    manifest_digest: str,
    manifest_size: int,
) -> bytes:
    request = source["storage_request"]
    receipt = {
        "receipt_schema": "scopecat.calibration_parameter_state_storage_receipt.v0",
        "request_id": request["request_id"],
        "approval_state": request["approval"]["approval_state"],
        "state_id": intake_summary["managed_parameter_state"]["state_id"],
        "source_intake_review_id": intake_summary["intake_review"]["review_id"],
        "source_handoff_id": intake_summary["source_handoff"]["handoff_id"],
        "manifest": {
            "path": request["manifest_path"],
            "digest": manifest_digest,
            "size_bytes": manifest_size,
        },
        "collision_policy": request["destination"]["collision_policy"],
        "storage_mutation": "performed",
        "non_claims": {
            "final_storage_architecture": "not_defined",
            "external_compatibility_output": "not_produced",
            "hardware_write_back": "not_performed",
            "rollback": "not_defined",
        },
    }
    return json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _validate_declared_expected_results(
    source: dict[str, Any],
    manifest_digest: str,
    receipt_digest: str,
) -> None:
    expected = source.get("expected_write_results")
    if expected is None:
        return
    by_kind = {item["kind"]: item for item in expected}
    if set(by_kind) != {"parameter_state_manifest", "write_receipt"}:
        raise ValueError("expected write results must name manifest and receipt")
    for item in by_kind.values():
        if not _SHA256_DIGEST.fullmatch(item["digest"]):
            raise ValueError("expected write result digest must be sha256-prefixed hex")
    if by_kind["parameter_state_manifest"]["digest"] != manifest_digest:
        raise ValueError("expected manifest digest does not match deterministic content")
    if by_kind["write_receipt"]["digest"] != receipt_digest:
        raise ValueError("expected receipt digest does not match deterministic content")


def _ensure_new_targets(source: dict[str, Any], storage_root: Path) -> None:
    request = source["storage_request"]
    reject_existing_paths(
        storage_root,
        [request["state_dir"], request["manifest_path"], request["receipt_path"]],
        "calibration parameter-state storage",
    )


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "calibration_parameter_state_storage_write_performed",
            "severity": "review",
            "basis": "Approved fixture input wrote a calibration-derived parameter-state storage directory.",
            "does_not_claim": "final_storage_architecture",
        },
        {
            "code": "no_overwrite_storage",
            "severity": "review",
            "basis": "Existing state directory, manifest, or receipt targets are refused.",
            "does_not_claim": "overwrite_merge_or_update",
        },
        {
            "code": "calibration_provenance_preserved",
            "severity": "info",
            "basis": "Calibration handoff, step, observation, and review identities are carried as provenance.",
            "does_not_claim": "measurement_payload_read_or_fit_execution",
        },
        {
            "code": "compatibility_output_not_produced",
            "severity": "review",
            "basis": "Persisting calibration-derived parameter state does not emit external compatibility files.",
            "does_not_claim": "external_parameter_file",
        },
        {
            "code": "hardware_write_back_not_performed",
            "severity": "review",
            "basis": "Persisting parameter state does not apply parameters to instruments.",
            "does_not_claim": "instrument_command_or_current_hardware_state",
        },
    ]


def write_calibration_parameter_state_storage(
    source: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    """Write one calibration-derived parameter-state summary under a caller root."""
    intake_summary = build_calibration_parameter_state_intake_summary(
        source["calibration_parameter_state_intake_input"]
    )
    _validate_references(source, intake_summary)
    storage_root_resolved = existing_directory_root(
        storage_root, "calibration parameter-state storage writer storage"
    )
    _ensure_new_targets(source, storage_root_resolved)

    manifest_content = _manifest_bytes(source, intake_summary)
    manifest_digest = _sha256_digest(manifest_content)
    receipt_content = _receipt_bytes(source, intake_summary, manifest_digest, len(manifest_content))
    receipt_digest = _sha256_digest(receipt_content)
    _validate_declared_expected_results(source, manifest_digest, receipt_digest)

    request = source["storage_request"]
    write_new_files_transaction(
        storage_root_resolved,
        [
            (request["manifest_path"], manifest_content),
            (request["receipt_path"], receipt_content),
        ],
        label="calibration parameter-state storage",
    )

    state = intake_summary["managed_parameter_state"]
    return {
        "storage_policy": copy.deepcopy(source["storage_policy"]),
        "storage_request": {
            "request_id": request["request_id"],
            "approval_state": request["approval"]["approval_state"],
            "state_dir": request["state_dir"],
            "manifest_path": request["manifest_path"],
            "receipt_path": request["receipt_path"],
            "collision_policy": request["destination"]["collision_policy"],
            "source_intake_review_id": request["source_intake_review_id"],
            "source_handoff_id": request["source_handoff_id"],
        },
        "parameter_state": {
            "state_id": state["state_id"],
            "state_kind": state["state_kind"],
            "state_label": state["state_label"],
            "readiness": state["readiness"],
            "trust_status": state["trust_status"],
            "entry_count": len(state["entries"]),
            "changed_entry_paths": [entry["path"] for entry in intake_summary["changed_entries"]],
            "trusted_entry_paths": list(state["trusted_entry_paths"]),
            "classification": "stored_calibration_derived_ready_for_review",
        },
        "write_results": [
            {
                "path": request["manifest_path"],
                "kind": "parameter_state_manifest",
                "result": "written",
                "bytes_written": len(manifest_content),
                "digest": manifest_digest,
                "does_not_claim": "final_parameter_state_storage_schema",
            },
            {
                "path": request["receipt_path"],
                "kind": "write_receipt",
                "result": "written",
                "bytes_written": len(receipt_content),
                "digest": receipt_digest,
                "does_not_claim": "final_storage_receipt_schema",
            },
        ],
        "provenance": copy.deepcopy(intake_summary["provenance"]),
        "source_handoff": copy.deepcopy(intake_summary["source_handoff"]),
        "attention": _attention(),
    }
