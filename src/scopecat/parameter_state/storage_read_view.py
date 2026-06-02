"""Read-only parameter-state storage view implementation candidate.

This module reads one explicitly declared stored parameter-state manifest and
write receipt under a caller-provided storage root. It deliberately does not
scan storage, mutate files, observe legacy sources, migrate schemas, write
hardware, open GUIs, or define final storage architecture.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scopecat.parameter_state._contracts import (
    relative_path_parts,
    validate_non_negative_integer,
    validate_relative_path,
    validate_sha256_digest,
)
from scopecat.parameter_state._storage import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
)

_EXPECTED_POLICY = {
    "read_authority": "explicit_parameter_state_storage_reference",
    "storage_root_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "manifest_observation": "explicit_manifest_and_receipt_files_only",
    "checksum_algorithm": "sha256",
    "storage_mutation": "not_performed",
    "catalog_discovery": "not_performed",
    "legacy_source_observation": "not_performed",
    "schema_migration": "not_performed",
    "external_file_authority": "not_claimed",
    "hardware_write_back": "not_performed",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_MANIFEST_SCHEMA = "scopecat.parameter_state_storage_manifest.v0"
_RECEIPT_SCHEMA = "scopecat.parameter_state_storage_receipt.v0"


@dataclass(frozen=True, init=False)
class ParameterStateStorageReadRequest:
    """Typed route-local request for an explicit manifest/receipt read."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> ParameterStateStorageReadRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)

    @property
    def state_id(self) -> str:
        return self._source["read_request"]["state_id"]

    @property
    def manifest_path(self) -> str:
        return self._source["read_request"]["manifest_path"]

    @property
    def receipt_path(self) -> str:
        return self._source["read_request"]["receipt_path"]


@dataclass(frozen=True, init=False)
class ParameterStateStorageReadResult:
    """Typed route-local result for a deterministic storage read view."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def classification(self) -> str:
        return self._summary["classification"]

    @property
    def review_findings(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["review_findings"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["read_view_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected parameter state storage read-view policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"parameter state storage read-view policy {key} must be {expected}")


def _validate_read_request(source: dict[str, Any]) -> None:
    request = source["read_request"]
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
    _validate_read_request(source)


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
                f"Declared {owner.replace('_', ' ')} file could not be observed "
                "under the caller root.",
                "repair_or_catalog_discovery",
            )
        ]
    findings = []
    if observed["observed_digest"] != expected_digest:
        findings.append(
            _finding(
                f"{owner}_digest_mismatch",
                f"Observed {owner.replace('_', ' ')} sha256 digest differs from "
                "the declared digest.",
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


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest["manifest_schema"] != _MANIFEST_SCHEMA:
        raise ValueError(f"parameter state manifest_schema must be {_MANIFEST_SCHEMA}")
    state = manifest["state"]
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
    if manifest["provenance"]["source_observation"] != "adapter_declared_only":
        raise ValueError(
            "parameter state manifest source observation must stay adapter_declared_only"
        )
    source_ids = {item["source_id"] for item in manifest["provenance"]["legacy_sources"]}
    if len(source_ids) != len(manifest["provenance"]["legacy_sources"]):
        raise ValueError("parameter state manifest provenance contains duplicate source_id")
    for entry in state["entries"]:
        for source_id in entry["source_ids"]:
            if source_id not in source_ids:
                raise ValueError(
                    "parameter state manifest entry references missing provenance source"
                )
    for excluded in manifest["excluded_preview_entries"]:
        for source_id in excluded["source_ids"]:
            if source_id not in source_ids:
                raise ValueError(
                    "parameter state manifest excluded entry references missing provenance source"
                )
    for key, expected in {
        "legacy_source_parsing": "not_performed",
        "schema_migration": "not_performed",
        "external_file_authority": "not_claimed",
        "hardware_write_back": "not_performed",
    }.items():
        if manifest["storage_non_claims"][key] != expected:
            raise ValueError(f"parameter state manifest non-claim {key} must be {expected}")


def _validate_receipt_shape(receipt: dict[str, Any]) -> None:
    if receipt["receipt_schema"] != _RECEIPT_SCHEMA:
        raise ValueError(f"parameter state receipt_schema must be {_RECEIPT_SCHEMA}")
    validate_sha256_digest(receipt["manifest"]["digest"], "receipt manifest digest")
    validate_non_negative_integer(receipt["manifest"]["size_bytes"], "receipt manifest size_bytes")
    if receipt["storage_mutation"] != "performed":
        raise ValueError("parameter state receipt storage_mutation must be performed")
    if receipt["non_claims"]["final_storage_architecture"] != "not_defined":
        raise ValueError("parameter state receipt final_storage_architecture must be not_defined")
    if receipt["non_claims"]["hardware_write_back"] != "not_performed":
        raise ValueError("parameter state receipt hardware_write_back must be not_performed")
    if receipt["non_claims"]["schema_migration"] != "not_performed":
        raise ValueError("parameter state receipt schema_migration must be not_performed")


def _continuity_findings(
    source: dict[str, Any],
    manifest_observed: dict[str, Any],
    receipt_observed: dict[str, Any],
    manifest: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> list[dict[str, str]]:
    request = source["read_request"]
    findings = []
    findings.extend(
        _file_findings(
            manifest_observed,
            request["expected_manifest_digest"],
            request["expected_manifest_size_bytes"],
            "manifest",
        )
    )
    findings.extend(
        _file_findings(
            receipt_observed,
            request["expected_receipt_digest"],
            request["expected_receipt_size_bytes"],
            "receipt",
        )
    )
    if manifest is None or receipt is None:
        return findings
    if receipt["manifest"]["path"] != request["manifest_path"]:
        findings.append(
            _finding(
                "receipt_manifest_path_mismatch",
                "Receipt manifest path does not match the explicit read request.",
                "repair_or_catalog_discovery",
            )
        )
    if receipt["manifest"]["digest"] != request["expected_manifest_digest"]:
        findings.append(
            _finding(
                "receipt_manifest_declared_digest_mismatch",
                "Receipt manifest digest does not match the explicit read request.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["size_bytes"] != request["expected_manifest_size_bytes"]:
        findings.append(
            _finding(
                "receipt_manifest_declared_size_mismatch",
                "Receipt manifest size does not match the explicit read request.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["digest"] != manifest_observed["observed_digest"]:
        findings.append(
            _finding(
                "receipt_manifest_digest_mismatch",
                "Receipt manifest digest does not match the observed manifest digest.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["manifest"]["size_bytes"] != manifest_observed["observed_size_bytes"]:
        findings.append(
            _finding(
                "receipt_manifest_size_mismatch",
                "Receipt manifest size does not match the observed manifest size.",
                "repair_or_cause_attribution",
            )
        )
    if receipt["state_id"] != manifest["state"]["state_id"]:
        findings.append(
            _finding(
                "receipt_state_id_mismatch",
                "Receipt state_id does not match the manifest state_id.",
                "repair_or_cause_attribution",
            )
        )
    if request["state_id"] != manifest["state"]["state_id"]:
        findings.append(
            _finding(
                "requested_state_id_mismatch",
                "Requested state_id does not match the manifest state_id.",
                "repair_or_cause_attribution",
            )
        )
    if request["state_id"] != receipt["state_id"]:
        findings.append(
            _finding(
                "requested_receipt_state_id_mismatch",
                "Requested state_id does not match the receipt state_id.",
                "repair_or_cause_attribution",
            )
        )
    return findings


def _classification(
    manifest_observed: dict[str, Any],
    receipt_observed: dict[str, Any],
    findings: list[dict[str, str]],
) -> str:
    if manifest_observed["status"] == "unavailable" or receipt_observed["status"] == "unavailable":
        return "stored_parameter_state_unavailable_for_review"
    if findings:
        return "stored_parameter_state_observed_with_mismatch"
    return "stored_parameter_state_read_view_ready"


def _state_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
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
        "source_preview_candidate_state_id": state["source_preview_candidate_state_id"],
        "created_by_review_id": state["created_by_review_id"],
        "trusted_entry_paths": list(state["trusted_entry_paths"]),
        "entry_count": len(state["entries"]),
    }


def _trusted_entries(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    return copy.deepcopy(manifest["state"]["entries"])


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "explicit_manifest_and_receipt_read",
            "severity": "review",
            "basis": "Only the declared manifest and receipt files are read.",
            "does_not_claim": "catalog_discovery_or_storage_scan",
        },
        {
            "code": "checksum_continuity_checked",
            "severity": "info",
            "basis": "Observed sha256 and size facts are compared with request and receipt facts.",
            "does_not_claim": "final_storage_integrity_contract",
        },
        {
            "code": "legacy_source_observation_not_performed",
            "severity": "review",
            "basis": "Legacy source references remain provenance and are not opened.",
            "does_not_claim": "source_file_checksum_or_availability",
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


def read_parameter_state_storage_view(
    source: dict[str, Any], *, storage_root: Path
) -> dict[str, Any]:
    """Read one explicitly referenced stored parameter-state manifest and receipt."""
    request_model = ParameterStateStorageReadRequest.from_dict(source)
    source = request_model.source
    storage_root_resolved = existing_directory_root(
        storage_root, "parameter state storage read-view storage"
    )
    request = source["read_request"]
    manifest_observed = _read_declared_file(
        storage_root_resolved,
        request["manifest_path"],
        "parameter state storage read-view manifest",
    )
    receipt_observed = _read_declared_file(
        storage_root_resolved,
        request["receipt_path"],
        "parameter state storage read-view receipt",
    )
    manifest = _load_json_observed(manifest_observed, "parameter state manifest")
    receipt = _load_json_observed(receipt_observed, "parameter state receipt")
    if manifest is not None:
        _validate_manifest_shape(manifest)
    if receipt is not None:
        _validate_receipt_shape(receipt)

    findings = _continuity_findings(source, manifest_observed, receipt_observed, manifest, receipt)
    summary = {
        "read_view_policy": copy.deepcopy(source["read_view_policy"]),
        "read_request": copy.deepcopy(request),
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
        "classification": _classification(manifest_observed, receipt_observed, findings),
        "parameter_state": _state_summary(manifest),
        "trusted_entries": _trusted_entries(manifest),
        "provenance": copy.deepcopy(manifest["provenance"]) if manifest is not None else None,
        "excluded_preview_entries": (
            copy.deepcopy(manifest["excluded_preview_entries"]) if manifest is not None else []
        ),
        "source_review": copy.deepcopy(manifest["source_review"]) if manifest is not None else None,
        "receipt": {
            "request_id": receipt["request_id"],
            "approval_state": receipt["approval_state"],
            "state_id": receipt["state_id"],
            "manifest_path": receipt["manifest"]["path"],
            "manifest_digest": receipt["manifest"]["digest"],
            "manifest_size_bytes": receipt["manifest"]["size_bytes"],
            "storage_mutation": receipt["storage_mutation"],
            "collision_policy": receipt["collision_policy"],
        }
        if receipt is not None
        else None,
        "review_findings": findings,
        "attention": _attention(),
    }
    return ParameterStateStorageReadResult(summary=summary).to_dict()
