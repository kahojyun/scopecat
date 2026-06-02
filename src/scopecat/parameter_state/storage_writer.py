"""Bounded parameter-state storage writer implementation candidate.

This module writes one reviewed managed parameter-state summary under a
caller-provided storage root. It deliberately does not parse legacy files,
perform schema migration, claim external file authority, write hardware, open
GUIs, or define final storage architecture.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from scopecat.parameter_state._storage import (
    existing_directory_root,
    reject_existing_paths,
    write_new_files_transaction,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_parameter_state_storage_write",
    "input_authority": "reviewed_managed_parameter_state_summary",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "overwrite_behavior": "no_overwrite",
    "checksum_algorithm": "sha256",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "schema_migration": "not_performed",
    "external_file_authority": "not_claimed",
    "hardware_write_back": "not_performed",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANAGED_STATE_KINDS = {"seed_snapshot", "committed_snapshot"}
_READINESS = {"seeded_incomplete", "partially_calibrated"}
_TRUST_STATUS = {"trusted_for_declared_scope", "not_fully_trusted"}


@dataclass(frozen=True, init=False)
class ParameterStateStorageWriteRequest:
    """Typed route-local request for an approved parameter-state storage write."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> ParameterStateStorageWriteRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)

    @property
    def state_id(self) -> str:
        return self._source["reviewed_managed_parameter_state"]["state_id"]

    @property
    def state_dir(self) -> str:
        return self._source["storage_request"]["state_dir"]

    @property
    def manifest_path(self) -> str:
        return self._source["storage_request"]["manifest_path"]

    @property
    def receipt_path(self) -> str:
        return self._source["storage_request"]["receipt_path"]


@dataclass(frozen=True, init=False)
class ParameterStateStorageWriteResult:
    """Typed route-local result for a completed no-overwrite storage write."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def state_id(self) -> str:
        return self._summary["parameter_state"]["state_id"]

    @property
    def write_results(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["write_results"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    raw_parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw_parts)
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["storage_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected parameter state storage writer policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"parameter state storage writer policy {key} must be {expected}")


def _validate_storage_request(source: dict[str, Any]) -> None:
    request = source["storage_request"]
    if request["approval"]["approval_state"] != "approved":
        raise ValueError("parameter state storage write request must be approved")
    destination = request["destination"]
    if destination["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("parameter state storage destination path kind must stay relative")
    if destination["collision_policy"] != "no_overwrite":
        raise ValueError("parameter state storage collision policy must refuse overwrites")

    for path_field in ("state_dir", "manifest_path", "receipt_path"):
        _validate_relative_path(request[path_field], f"storage request {path_field}")
    state_dir = request["state_dir"]
    for path_field in ("manifest_path", "receipt_path"):
        path = request[path_field]
        if not path.startswith(f"{state_dir}/"):
            raise ValueError(f"storage request {path_field} must stay under state_dir")
    if request["manifest_path"] == request["receipt_path"]:
        raise ValueError("parameter state manifest and receipt paths must differ")
    manifest_parts = _relative_parts(request["manifest_path"])
    receipt_parts = _relative_parts(request["receipt_path"])
    if (
        manifest_parts[: len(receipt_parts)] == receipt_parts
        or receipt_parts[: len(manifest_parts)] == manifest_parts
    ):
        raise ValueError("parameter state storage output paths must not overlap")


def _validate_managed_state(source: dict[str, Any]) -> None:
    state = source["reviewed_managed_parameter_state"]
    if state["state_kind"] not in _MANAGED_STATE_KINDS:
        raise ValueError(f"unsupported parameter state kind: {state['state_kind']}")
    if state["readiness"] not in _READINESS:
        raise ValueError("parameter state readiness is unsupported")
    if state["trust_status"] not in _TRUST_STATUS:
        raise ValueError("parameter state trust_status is unsupported")
    if not state["source_preview_candidate_state_id"]:
        raise ValueError("parameter state requires source_preview_candidate_state_id")
    if not state["created_by_review_id"]:
        raise ValueError("parameter state requires created_by_review_id")
    if not state["lineage"]["lineage_id"]:
        raise ValueError("parameter state lineage requires lineage_id")

    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError("parameter state contains duplicate entry path")
    trusted_paths = state["trusted_entry_paths"]
    if len(trusted_paths) != len(set(trusted_paths)):
        raise ValueError("parameter state contains duplicate trusted entry path")
    if set(trusted_paths) != set(entry_paths):
        raise ValueError("parameter state trusted paths must match entries")
    for entry in state["entries"]:
        if entry["trust"] != "review_accepted":
            raise ValueError("stored parameter state entries must be review_accepted")
        if not entry["source_ids"]:
            raise ValueError("stored parameter state entries require source_ids")


def _validate_provenance(source: dict[str, Any]) -> None:
    provenance = source["provenance"]
    if provenance["source_observation"] != "adapter_declared_only":
        raise ValueError(
            "parameter state storage source observation must stay adapter_declared_only"
        )
    source_ids = {item["source_id"] for item in provenance["legacy_sources"]}
    if len(source_ids) != len(provenance["legacy_sources"]):
        raise ValueError("parameter state provenance contains duplicate source_id")
    for entry in source["reviewed_managed_parameter_state"]["entries"]:
        for source_id in entry["source_ids"]:
            if source_id not in source_ids:
                raise ValueError("parameter state entry references missing provenance source")
    for excluded in source["excluded_preview_entries"]:
        for source_id in excluded["source_ids"]:
            if source_id not in source_ids:
                raise ValueError("excluded preview entry references missing provenance source")


def _validate_side_effects(source: dict[str, Any]) -> None:
    side_effects = source["side_effect_claims"]
    for key in (
        "legacy_source_parsing",
        "schema_migration",
        "hardware_write_back",
        "storage_mutation",
    ):
        expected = "performed" if key == "storage_mutation" else "not_performed"
        if side_effects[key] != expected:
            raise ValueError(f"side effect claim {key} must be {expected}")
    if side_effects["external_file_authority"] != "not_claimed":
        raise ValueError("side effect claim external_file_authority must be not_claimed")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_storage_request(source)
    _validate_managed_state(source)
    _validate_provenance(source)
    _validate_side_effects(source)


def _manifest_bytes(source: dict[str, Any]) -> bytes:
    manifest = {
        "manifest_schema": "scopecat.parameter_state_storage_manifest.v0",
        "state": copy.deepcopy(source["reviewed_managed_parameter_state"]),
        "provenance": copy.deepcopy(source["provenance"]),
        "excluded_preview_entries": copy.deepcopy(source["excluded_preview_entries"]),
        "source_review": {
            "review_id": source["review"]["review_id"],
            "review_status": source["review"]["review_status"],
            "accepted_at": source["review"]["accepted_at"],
            "accepted_by_role": source["review"]["accepted_by_role"],
        },
        "storage_non_claims": {
            "legacy_source_parsing": "not_performed",
            "schema_migration": "not_performed",
            "external_file_authority": "not_claimed",
            "hardware_write_back": "not_performed",
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _receipt_bytes(
    source: dict[str, Any],
    manifest_digest: str,
    manifest_size: int,
) -> bytes:
    request = source["storage_request"]
    receipt = {
        "receipt_schema": "scopecat.parameter_state_storage_receipt.v0",
        "request_id": request["request_id"],
        "approval_state": request["approval"]["approval_state"],
        "state_id": source["reviewed_managed_parameter_state"]["state_id"],
        "manifest": {
            "path": request["manifest_path"],
            "digest": manifest_digest,
            "size_bytes": manifest_size,
        },
        "collision_policy": request["destination"]["collision_policy"],
        "storage_mutation": "performed",
        "non_claims": {
            "final_storage_architecture": "not_defined",
            "schema_migration": "not_performed",
            "hardware_write_back": "not_performed",
        },
    }
    return json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "parameter_state_storage_write_performed",
            "severity": "review",
            "basis": "Approved fixture input wrote a new parameter-state storage directory.",
            "does_not_claim": "final_storage_architecture",
        },
        {
            "code": "no_overwrite_storage",
            "severity": "review",
            "basis": "Existing state directory, manifest, or receipt targets are refused.",
            "does_not_claim": "overwrite_merge_or_update",
        },
        {
            "code": "reviewed_summary_authority",
            "severity": "review",
            "basis": "The writer consumes reviewed managed parameter-state summary input.",
            "does_not_claim": "legacy_parser_or_review_engine",
        },
        {
            "code": "source_provenance_preserved",
            "severity": "info",
            "basis": "Adapter and legacy-source references are carried as provenance.",
            "does_not_claim": "source_file_observation_or_checksum",
        },
        {
            "code": "hardware_write_back_not_performed",
            "severity": "review",
            "basis": "Persisting parameter state does not apply parameters to instruments.",
            "does_not_claim": "instrument_command_or_current_hardware_state",
        },
    ]


def _ensure_new_targets(source: dict[str, Any], storage_root: Path) -> None:
    request = source["storage_request"]
    reject_existing_paths(
        storage_root,
        [request["state_dir"], request["manifest_path"], request["receipt_path"]],
        "parameter state storage",
    )


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
    if not _SHA256_DIGEST.fullmatch(by_kind["parameter_state_manifest"]["digest"]):
        raise ValueError("expected manifest digest must be sha256-prefixed hex")
    if not _SHA256_DIGEST.fullmatch(by_kind["write_receipt"]["digest"]):
        raise ValueError("expected receipt digest must be sha256-prefixed hex")
    if by_kind["parameter_state_manifest"]["digest"] != manifest_digest:
        raise ValueError("expected manifest digest does not match deterministic content")
    if by_kind["write_receipt"]["digest"] != receipt_digest:
        raise ValueError("expected receipt digest does not match deterministic content")


def write_parameter_state_storage(
    source: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    """Write one reviewed parameter-state summary under a caller-provided root."""
    request_model = ParameterStateStorageWriteRequest.from_dict(source)
    source = request_model.source
    storage_root_resolved = existing_directory_root(
        storage_root, "parameter state storage writer storage"
    )
    _ensure_new_targets(source, storage_root_resolved)

    manifest_content = _manifest_bytes(source)
    manifest_digest = f"sha256:{hashlib.sha256(manifest_content).hexdigest()}"
    receipt_content = _receipt_bytes(source, manifest_digest, len(manifest_content))
    receipt_digest = f"sha256:{hashlib.sha256(receipt_content).hexdigest()}"
    _validate_declared_expected_results(source, manifest_digest, receipt_digest)

    request = source["storage_request"]
    write_new_files_transaction(
        storage_root_resolved,
        [
            (request["manifest_path"], manifest_content),
            (request["receipt_path"], receipt_content),
        ],
        label="parameter state storage",
    )

    summary = {
        "storage_policy": copy.deepcopy(source["storage_policy"]),
        "storage_request": {
            "request_id": request["request_id"],
            "approval_state": request["approval"]["approval_state"],
            "state_dir": request["state_dir"],
            "manifest_path": request["manifest_path"],
            "receipt_path": request["receipt_path"],
            "collision_policy": request["destination"]["collision_policy"],
        },
        "parameter_state": {
            "state_id": source["reviewed_managed_parameter_state"]["state_id"],
            "state_kind": source["reviewed_managed_parameter_state"]["state_kind"],
            "state_label": source["reviewed_managed_parameter_state"]["state_label"],
            "readiness": source["reviewed_managed_parameter_state"]["readiness"],
            "trust_status": source["reviewed_managed_parameter_state"]["trust_status"],
            "entry_count": len(source["reviewed_managed_parameter_state"]["entries"]),
            "trusted_entry_paths": list(
                source["reviewed_managed_parameter_state"]["trusted_entry_paths"]
            ),
            "classification": "stored_ready_for_review",
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
        "provenance": copy.deepcopy(source["provenance"]),
        "excluded_preview_entries": copy.deepcopy(source["excluded_preview_entries"]),
        "attention": _attention(),
    }
    return ParameterStateStorageWriteResult(summary=summary).to_dict()
