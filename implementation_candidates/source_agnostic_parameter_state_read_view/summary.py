"""Source-agnostic parameter-state storage read view.

This implementation candidate reads explicitly declared stored parameter-state
manifest/receipt pairs and projects common state facts while preserving
source-specific provenance payloads. It accepts the existing adapter-derived
storage manifest and the calibration-derived storage manifest, without catalog
discovery, storage mutation, compatibility output, hardware write-back, or a
final storage schema.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts,
    validate_non_negative_integer,
    validate_relative_path,
    validate_sha256_digest,
)
from implementation_candidates.filesystem_mutation import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
)

_EXPECTED_POLICY = {
    "read_authority": "explicit_parameter_state_storage_references",
    "storage_root_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "manifest_observation": "explicit_manifest_and_receipt_files_only",
    "supported_manifest_sources": "adapter_and_calibration_derived",
    "checksum_algorithm": "sha256",
    "storage_mutation": "not_performed",
    "catalog_discovery": "not_performed",
    "compatibility_output": "not_produced",
    "hardware_write_back": "not_performed",
    "schema_migration": "not_performed",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_ADAPTER_MANIFEST_SCHEMA = "scopecat.parameter_state_storage_manifest.v0"
_ADAPTER_RECEIPT_SCHEMA = "scopecat.parameter_state_storage_receipt.v0"
_CALIBRATION_MANIFEST_SCHEMA = "scopecat.calibration_parameter_state_storage_manifest.v0"
_CALIBRATION_RECEIPT_SCHEMA = "scopecat.calibration_parameter_state_storage_receipt.v0"
_SUPPORTED_SOURCE_KINDS = {"adapter_import", "calibration_handoff"}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["read_view_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected source-agnostic parameter-state read-view policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"source-agnostic read-view policy {key} must be {expected}")


def _validate_read_request(request: dict[str, Any]) -> None:
    if request["source_kind"] not in _SUPPORTED_SOURCE_KINDS:
        raise ValueError("unsupported parameter-state source_kind")
    validate_relative_path(request["manifest_path"], "read request manifest_path")
    validate_relative_path(request["receipt_path"], "read request receipt_path")
    if request["manifest_path"] == request["receipt_path"]:
        raise ValueError("read request manifest and receipt paths must differ")
    manifest_parts = relative_path_parts(request["manifest_path"], "read request manifest_path")
    receipt_parts = relative_path_parts(request["receipt_path"], "read request receipt_path")
    if (
        manifest_parts[: len(receipt_parts)] == receipt_parts
        or receipt_parts[: len(manifest_parts)] == manifest_parts
    ):
        raise ValueError("read request manifest and receipt paths must not overlap")
    validate_sha256_digest(request["expected_manifest_digest"], "expected manifest digest")
    validate_sha256_digest(request["expected_receipt_digest"], "expected receipt digest")
    validate_non_negative_integer(
        request["expected_manifest_size_bytes"], "expected_manifest_size_bytes"
    )
    validate_non_negative_integer(
        request["expected_receipt_size_bytes"], "expected_receipt_size_bytes"
    )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    requests = source["read_requests"]
    if not requests:
        raise ValueError("source-agnostic read view requires at least one read request")
    request_ids = [request["request_id"] for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("duplicate read request_id")
    state_ids = [request["state_id"] for request in requests]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("duplicate requested state_id")
    for request in requests:
        _validate_read_request(request)


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _read_declared_file(storage_root: Path, relative_path: str, label: str) -> dict[str, Any]:
    ensure_no_symlink_parents(storage_root, relative_path, label)
    target = path_under(storage_root, relative_path)
    if target.is_symlink():
        raise ValueError(f"{label} target is a symlink")
    if not target.is_file():
        return {
            "path": relative_path,
            "status": "unavailable",
            "content": None,
            "observed_digest": None,
            "observed_size_bytes": None,
        }
    content = target.read_bytes()
    return {
        "path": relative_path,
        "status": "observed",
        "content": content,
        "observed_digest": _sha256_digest(content),
        "observed_size_bytes": len(content),
    }


def _load_json_observed(observed: dict[str, Any], label: str) -> dict[str, Any] | None:
    if observed["status"] != "observed":
        return None
    try:
        return json.loads(observed["content"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc


def _finding(code: str, basis: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _file_findings(
    observed: dict[str, Any],
    expected_digest: str,
    expected_size: int,
    owner: str,
) -> list[dict[str, str]]:
    if observed["status"] == "unavailable":
        return [
            _finding(
                f"{owner}_unavailable",
                f"Declared {owner.replace('_', ' ')} file could not be observed under the caller root.",
                "repair_or_catalog_discovery",
            )
        ]
    findings = []
    if observed["observed_digest"] != expected_digest:
        findings.append(
            _finding(
                f"{owner}_digest_mismatch",
                f"Observed {owner.replace('_', ' ')} sha256 digest differs from the declared digest.",
                "repair_or_cause_attribution",
            )
        )
    if observed["observed_size_bytes"] != expected_size:
        findings.append(
            _finding(
                f"{owner}_size_mismatch",
                f"Observed {owner.replace('_', ' ')} byte size differs from the declared size.",
                "repair_or_cause_attribution",
            )
        )
    return findings


def _manifest_source_kind(manifest: dict[str, Any]) -> str:
    schema = manifest["manifest_schema"]
    if schema == _ADAPTER_MANIFEST_SCHEMA:
        return "adapter_import"
    if schema == _CALIBRATION_MANIFEST_SCHEMA:
        return "calibration_handoff"
    raise ValueError("unsupported parameter-state manifest_schema")


def _validate_common_state(state: dict[str, Any]) -> None:
    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError("parameter state manifest contains duplicate entry path")
    trusted_paths = state["trusted_entry_paths"]
    if len(trusted_paths) != len(set(trusted_paths)):
        raise ValueError("parameter state manifest contains duplicate trusted entry path")
    if set(trusted_paths) != set(entry_paths):
        raise ValueError("parameter state manifest trusted paths must match entries")
    for entry in state["entries"]:
        if entry["trust"] != "review_accepted":
            raise ValueError("parameter state manifest entries must be review_accepted")
        if not entry["source_ids"]:
            raise ValueError("parameter state manifest entries require source_ids")


def _validate_adapter_manifest(manifest: dict[str, Any]) -> None:
    if manifest["manifest_schema"] != _ADAPTER_MANIFEST_SCHEMA:
        raise ValueError(f"adapter manifest_schema must be {_ADAPTER_MANIFEST_SCHEMA}")
    _validate_common_state(manifest["state"])
    if manifest["provenance"]["source_observation"] != "adapter_declared_only":
        raise ValueError("adapter provenance source_observation must stay adapter_declared_only")
    source_ids = {item["source_id"] for item in manifest["provenance"]["legacy_sources"]}
    if len(source_ids) != len(manifest["provenance"]["legacy_sources"]):
        raise ValueError("adapter provenance contains duplicate source_id")
    for entry in manifest["state"]["entries"]:
        for source_id in entry["source_ids"]:
            if source_id not in source_ids:
                raise ValueError("adapter entry references missing provenance source")
    for excluded in manifest["excluded_preview_entries"]:
        for source_id in excluded["source_ids"]:
            if source_id not in source_ids:
                raise ValueError("adapter excluded entry references missing provenance source")


def _validate_calibration_manifest(manifest: dict[str, Any]) -> None:
    if manifest["manifest_schema"] != _CALIBRATION_MANIFEST_SCHEMA:
        raise ValueError(f"calibration manifest_schema must be {_CALIBRATION_MANIFEST_SCHEMA}")
    _validate_common_state(manifest["state"])
    provenance = manifest["provenance"]
    if provenance["source_kind"] != "calibration_accepted_write_handoff":
        raise ValueError("calibration provenance source_kind is unsupported")
    if provenance["source_observation"] != "validated_calibration_handoff_summary":
        raise ValueError("calibration provenance source_observation is unsupported")
    if manifest["source_handoff"]["handoff_id"] != provenance["source_handoff_id"]:
        raise ValueError("calibration source_handoff must match provenance handoff")
    if manifest["source_review"]["review_id"] != manifest["state"]["created_by_review_id"]:
        raise ValueError("calibration source_review must match managed state review")
    allowed_sources = {
        f"calibration_handoff:{provenance['source_handoff_id']}",
        f"base_parameter_state:{provenance['base_state_id']}",
    }
    for entry in manifest["state"]["entries"]:
        for source_id in entry["source_ids"]:
            if source_id not in allowed_sources:
                raise ValueError("calibration entry references missing provenance source")


def _validate_manifest_shape(manifest: dict[str, Any], expected_source_kind: str) -> str:
    source_kind = _manifest_source_kind(manifest)
    if source_kind != expected_source_kind:
        raise ValueError("manifest source_kind does not match read request")
    if source_kind == "adapter_import":
        _validate_adapter_manifest(manifest)
    else:
        _validate_calibration_manifest(manifest)
    return source_kind


def _receipt_source_kind(receipt: dict[str, Any]) -> str:
    schema = receipt["receipt_schema"]
    if schema == _ADAPTER_RECEIPT_SCHEMA:
        return "adapter_import"
    if schema == _CALIBRATION_RECEIPT_SCHEMA:
        return "calibration_handoff"
    raise ValueError("unsupported parameter-state receipt_schema")


def _validate_receipt_shape(receipt: dict[str, Any], expected_source_kind: str) -> str:
    source_kind = _receipt_source_kind(receipt)
    if source_kind != expected_source_kind:
        raise ValueError("receipt source_kind does not match read request")
    validate_sha256_digest(receipt["manifest"]["digest"], "receipt manifest digest")
    validate_non_negative_integer(receipt["manifest"]["size_bytes"], "receipt manifest size_bytes")
    if receipt["storage_mutation"] != "performed":
        raise ValueError("parameter state receipt storage_mutation must be performed")
    if receipt["non_claims"]["final_storage_architecture"] != "not_defined":
        raise ValueError("parameter state receipt final_storage_architecture must be not_defined")
    if receipt["non_claims"]["hardware_write_back"] != "not_performed":
        raise ValueError("parameter state receipt hardware_write_back must be not_performed")
    return source_kind


def _continuity_findings(
    request: dict[str, Any],
    manifest_observed: dict[str, Any],
    receipt_observed: dict[str, Any],
    manifest: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> list[dict[str, str]]:
    findings = []
    findings.extend(
        _file_findings(
            manifest_observed,
            request["expected_manifest_digest"],
            request["expected_manifest_size_bytes"],
            f"{request['request_id']}_manifest",
        )
    )
    findings.extend(
        _file_findings(
            receipt_observed,
            request["expected_receipt_digest"],
            request["expected_receipt_size_bytes"],
            f"{request['request_id']}_receipt",
        )
    )
    if manifest is None or receipt is None:
        return findings
    if receipt["manifest"]["path"] != request["manifest_path"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_manifest_path_mismatch",
                "Receipt manifest path does not match the explicit read request.",
                "repair_or_catalog_discovery",
            )
        )
    if receipt["manifest"]["digest"] != request["expected_manifest_digest"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_manifest_declared_digest_mismatch",
                "Receipt manifest digest does not match the explicit read request.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["size_bytes"] != request["expected_manifest_size_bytes"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_manifest_declared_size_mismatch",
                "Receipt manifest size does not match the explicit read request.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["digest"] != manifest_observed["observed_digest"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_manifest_digest_mismatch",
                "Receipt manifest digest does not match the observed manifest digest.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["size_bytes"] != manifest_observed["observed_size_bytes"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_manifest_size_mismatch",
                "Receipt manifest size does not match the observed manifest size.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["state_id"] != manifest["state"]["state_id"]:
        findings.append(
            _finding(
                f"{request['request_id']}_receipt_state_id_mismatch",
                "Receipt state_id does not match the manifest state_id.",
                "repair_or_cause_attribution",
            )
        )
    if request["state_id"] != manifest["state"]["state_id"]:
        findings.append(
            _finding(
                f"{request['request_id']}_requested_state_id_mismatch",
                "Requested state_id does not match the manifest state_id.",
                "repair_or_cause_attribution",
            )
        )
    return findings


def _state_classification(
    manifest_observed: dict[str, Any],
    receipt_observed: dict[str, Any],
    findings: list[dict[str, str]],
) -> str:
    if manifest_observed["status"] == "unavailable" or receipt_observed["status"] == "unavailable":
        return "stored_parameter_state_unavailable_for_review"
    if findings:
        return "stored_parameter_state_observed_with_mismatch"
    return "stored_parameter_state_read_view_ready"


def _overall_classification(stored_states: list[dict[str, Any]]) -> str:
    classifications = {state["classification"] for state in stored_states}
    if classifications == {"stored_parameter_state_read_view_ready"}:
        return "all_explicit_parameter_states_ready"
    if "stored_parameter_state_unavailable_for_review" in classifications:
        return "one_or_more_parameter_states_unavailable_for_review"
    return "one_or_more_parameter_states_observed_with_mismatch"


def _observed_file_summary(
    observed: dict[str, Any],
    *,
    kind: str,
    expected_digest: str,
    expected_size: int,
) -> dict[str, Any]:
    return {
        "path": observed["path"],
        "kind": kind,
        "status": observed["status"],
        "expected_digest": expected_digest,
        "observed_digest": observed["observed_digest"],
        "expected_size_bytes": expected_size,
        "observed_size_bytes": observed["observed_size_bytes"],
    }


def _common_state_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    state = manifest["state"]
    return {
        "state_id": state["state_id"],
        "state_kind": state["state_kind"],
        "state_label": state["state_label"],
        "lineage": copy.deepcopy(state["lineage"]),
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "trusted_entry_paths": list(state["trusted_entry_paths"]),
        "entry_count": len(state["entries"]),
    }


def _typed_provenance(source_kind: str, manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    if source_kind == "adapter_import":
        return {
            "source_kind": "adapter_import",
            "payload": copy.deepcopy(manifest["provenance"]),
            "excluded_preview_entries": copy.deepcopy(manifest["excluded_preview_entries"]),
            "source_review": copy.deepcopy(manifest["source_review"]),
        }
    return {
        "source_kind": "calibration_handoff",
        "payload": copy.deepcopy(manifest["provenance"]),
        "source_review": copy.deepcopy(manifest["source_review"]),
        "source_handoff": copy.deepcopy(manifest["source_handoff"]),
        "changed_entries": copy.deepcopy(manifest["changed_entries"]),
    }


def _receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    summary = {
        "request_id": receipt["request_id"],
        "approval_state": receipt["approval_state"],
        "state_id": receipt["state_id"],
        "manifest_path": receipt["manifest"]["path"],
        "manifest_digest": receipt["manifest"]["digest"],
        "manifest_size_bytes": receipt["manifest"]["size_bytes"],
        "storage_mutation": receipt["storage_mutation"],
        "collision_policy": receipt["collision_policy"],
    }
    for key in ("source_intake_review_id", "source_handoff_id"):
        if key in receipt:
            summary[key] = receipt[key]
    return summary


def _read_one_state(
    request: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    manifest_observed = _read_declared_file(
        storage_root,
        request["manifest_path"],
        f"{request['request_id']} source-agnostic manifest",
    )
    receipt_observed = _read_declared_file(
        storage_root,
        request["receipt_path"],
        f"{request['request_id']} source-agnostic receipt",
    )
    manifest = _load_json_observed(manifest_observed, "parameter state manifest")
    receipt = _load_json_observed(receipt_observed, "parameter state receipt")
    if manifest is not None:
        _validate_manifest_shape(manifest, request["source_kind"])
    if receipt is not None:
        _validate_receipt_shape(receipt, request["source_kind"])

    findings = _continuity_findings(request, manifest_observed, receipt_observed, manifest, receipt)
    return {
        "read_request": copy.deepcopy(request),
        "classification": _state_classification(manifest_observed, receipt_observed, findings),
        "source_kind": request["source_kind"],
        "observed_files": [
            _observed_file_summary(
                manifest_observed,
                kind="parameter_state_manifest",
                expected_digest=request["expected_manifest_digest"],
                expected_size=request["expected_manifest_size_bytes"],
            ),
            _observed_file_summary(
                receipt_observed,
                kind="write_receipt",
                expected_digest=request["expected_receipt_digest"],
                expected_size=request["expected_receipt_size_bytes"],
            ),
        ],
        "parameter_state": _common_state_summary(manifest),
        "trusted_entries": copy.deepcopy(manifest["state"]["entries"])
        if manifest is not None
        else [],
        "typed_provenance": _typed_provenance(request["source_kind"], manifest),
        "receipt": _receipt_summary(receipt),
        "review_findings": findings,
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "explicit_manifest_and_receipt_read",
            "severity": "review",
            "basis": "Only declared manifest and receipt files are read for each requested state.",
            "does_not_claim": "catalog_discovery_or_storage_scan",
        },
        {
            "code": "typed_provenance_preserved",
            "severity": "info",
            "basis": "Adapter and calibration provenance are preserved as source-specific payloads.",
            "does_not_claim": "universal_provenance_schema",
        },
        {
            "code": "checksum_continuity_checked",
            "severity": "info",
            "basis": "Observed sha256 and size facts are compared with request and receipt facts.",
            "does_not_claim": "final_storage_integrity_contract",
        },
        {
            "code": "storage_mutation_not_performed",
            "severity": "review",
            "basis": "The read view does not write, repair, migrate, or update storage.",
            "does_not_claim": "storage_writer_or_catalog_update",
        },
        {
            "code": "hardware_write_back_not_performed",
            "severity": "review",
            "basis": "Reading parameter state does not apply parameters to instruments.",
            "does_not_claim": "instrument_command_or_current_hardware_state",
        },
    ]


def read_source_agnostic_parameter_state_view(
    source: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    """Read explicit adapter-derived and calibration-derived parameter states."""
    _validate_references(source)
    storage_root_resolved = existing_directory_root(
        storage_root, "source-agnostic parameter-state read-view storage"
    )
    stored_states = [
        _read_one_state(request, storage_root=storage_root_resolved)
        for request in source["read_requests"]
    ]
    return {
        "read_view_policy": copy.deepcopy(source["read_view_policy"]),
        "classification": _overall_classification(stored_states),
        "stored_states": stored_states,
        "review_findings": [
            {"request_id": state["read_request"]["request_id"], **finding}
            for state in stored_states
            for finding in state["review_findings"]
        ],
        "attention": _attention(),
    }
