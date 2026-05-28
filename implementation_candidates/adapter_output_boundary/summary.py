"""Adapter-produced output boundary validation candidate.

This module validates a file-shaped fixture for adapter-produced output. The
file shape is transport pressure only; the earned contract is the logical set
of adapter facts and declared files that could later be supplied by a
writer-like API.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from implementation_candidates.adapter_authored_legacy_import import (
    build_adapter_authored_legacy_import_summary,
)
from implementation_candidates.contract_primitives import (
    relative_path_parts as _relative_parts,
)
from implementation_candidates.contract_primitives import (
    validate_public_identifier,
    validate_sha256_digest,
)
from implementation_candidates.contract_primitives import (
    validate_relative_path as _validate_relative_path,
)

_BOUNDARY_SCHEMA = "scopecat.adapter_output_boundary.v0"
_BOUNDARY_MANIFEST = "adapter-output-boundary.json"

_EXPECTED_POLICY = {
    "adapter_output_authority": "adapter_produced_boundary",
    "transport_shape": "file_bundle_fixture",
    "final_transport_api": "not_decided",
    "writer_like_api_compatibility": "logical_contract_only",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "manifest_validation": "adapter_authored_legacy_import_manifest",
    "file_observation": "declared_adapter_output_files",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "reference_repair": "not_performed",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}

_EXPECTED_TRANSPORT = {
    "fixture_shape": "file_bundle",
    "final_transport": "not_decided",
    "writer_like_api": "logical_contract_compatible",
}

_DECLARED_FILE_ROLES = {
    "adapter_manifest",
    "normalized_primary_data",
}


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("adapter output root must not be a symlink")
    if not root.is_dir():
        raise ValueError("adapter output root must be an existing directory")
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("adapter output parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("adapter output parent is not a directory")


def _read_json_file(root: Path, relative_path: str) -> dict[str, Any]:
    _validate_relative_path(relative_path, "adapter output json")
    _ensure_no_symlink_parents(root, relative_path)
    path = _path_under(root, relative_path)
    if path.is_symlink():
        raise ValueError("adapter output json target is a symlink")
    if not path.is_file():
        raise ValueError(f"adapter output json is unavailable: {relative_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["adapter_output_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("adapter output policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"adapter output policy {key} must be {expected}")


def _validate_transport(source: dict[str, Any]) -> None:
    transport = source["transport"]
    if set(transport) != set(_EXPECTED_TRANSPORT):
        raise ValueError("adapter output transport must match expected shape")
    for key, expected in _EXPECTED_TRANSPORT.items():
        if transport[key] != expected:
            raise ValueError(f"adapter output transport {key} must be {expected}")


def _validate_declared_file(file_record: dict[str, Any], owner: str) -> None:
    validate_public_identifier(file_record["file_id"], f"{owner} file_id")
    _validate_relative_path(file_record["path"], f"{owner} path")
    if file_record["role"] not in _DECLARED_FILE_ROLES:
        raise ValueError(f"{owner} role is unsupported")
    if file_record["authority"] != "adapter_declared":
        raise ValueError(f"{owner} authority must stay adapter_declared")
    if file_record["required"] is not True:
        raise ValueError(f"{owner} must be required")
    validate_sha256_digest(file_record["digest"], f"{owner} digest")
    if not isinstance(file_record["size_bytes"], int) or file_record["size_bytes"] <= 0:
        raise ValueError(f"{owner} size_bytes must be positive")


def _validate_linked_context_ref(ref: dict[str, Any], owner: str) -> None:
    validate_public_identifier(ref["link_id"], f"{owner} link_id")
    _validate_relative_path(ref["path"], f"{owner} path")
    if ref["authority"] != "adapter_declared":
        raise ValueError(f"{owner} authority must stay adapter_declared")
    if ref["payload_import"] != "not_performed":
        raise ValueError(f"{owner} payload_import must be not_performed")
    validate_sha256_digest(ref["digest"], f"{owner} digest")
    if not isinstance(ref["size_bytes"], int) or ref["size_bytes"] <= 0:
        raise ValueError(f"{owner} size_bytes must be positive")


def _validate_boundary_manifest(source: dict[str, Any]) -> None:
    if source["adapter_output_schema"] != _BOUNDARY_SCHEMA:
        raise ValueError(f"adapter_output_schema must be {_BOUNDARY_SCHEMA}")
    _validate_policy(source)
    _validate_transport(source)
    _validate_relative_path(source["adapter_manifest_path"], "adapter_manifest_path")

    declared_files = source["declared_files"]
    if not isinstance(declared_files, list) or len(declared_files) != 2:
        raise ValueError("adapter output must declare manifest and primary data files")
    roles = {file_record["role"] for file_record in declared_files}
    if roles != _DECLARED_FILE_ROLES:
        raise ValueError("adapter output declared file roles must match expected set")
    for file_record in declared_files:
        _validate_declared_file(file_record, f"declared file {file_record['file_id']}")
    manifest_files = [
        file_record for file_record in declared_files if file_record["role"] == "adapter_manifest"
    ]
    if manifest_files[0]["path"] != source["adapter_manifest_path"]:
        raise ValueError("adapter manifest declared file must match adapter_manifest_path")

    refs = source["linked_context_refs"]
    if not isinstance(refs, list):
        raise ValueError("adapter output linked_context_refs must be a list")
    seen_refs = set()
    for ref in refs:
        _validate_linked_context_ref(ref, f"linked context ref {ref['link_id']}")
        if ref["link_id"] in seen_refs:
            raise ValueError(f"duplicate linked context ref: {ref['link_id']}")
        seen_refs.add(ref["link_id"])


def _observe_file(root: Path, declared: dict[str, Any]) -> dict[str, Any]:
    relative_path = declared["path"]
    _ensure_no_symlink_parents(root, relative_path)
    target = _path_under(root, relative_path)
    if target.is_symlink():
        raise ValueError("adapter output target is a symlink")
    if not target.is_file():
        return {
            "file_id": declared["file_id"],
            "role": declared["role"],
            "path": relative_path,
            "status": "unavailable",
            "expected_digest": declared["digest"],
            "observed_digest": None,
            "expected_size_bytes": declared["size_bytes"],
            "observed_size_bytes": None,
        }
    return {
        "file_id": declared["file_id"],
        "role": declared["role"],
        "path": relative_path,
        "status": "observed",
        "expected_digest": declared["digest"],
        "observed_digest": _sha256_digest(target),
        "expected_size_bytes": declared["size_bytes"],
        "observed_size_bytes": target.stat().st_size,
    }


def _observe_declared_files(root: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    return [_observe_file(root, declared) for declared in source["declared_files"]]


def _declared_file_path_by_role(source: dict[str, Any], role: str) -> str:
    return next(
        declared["path"] for declared in source["declared_files"] if declared["role"] == role
    )


def _observe_linked_context_refs(root: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    observed_refs = []
    for ref in source["linked_context_refs"]:
        observed = _observe_file(
            root,
            {
                "file_id": ref["link_id"],
                "role": "linked_context_reference",
                "path": ref["path"],
                "digest": ref["digest"],
                "size_bytes": ref["size_bytes"],
            },
        )
        observed["payload_import"] = ref["payload_import"]
        observed_refs.append(observed)
    return observed_refs


def _finding(code: str, target: str, message: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
        "does_not_claim": does_not_claim,
    }


def _file_findings(observed_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    for observed in observed_files:
        if observed["status"] == "unavailable":
            findings.append(
                _finding(
                    "adapter_output_file_unavailable",
                    observed["path"],
                    "A declared adapter output file is unavailable.",
                    "path_repair_or_legacy_source_discovery",
                )
            )
            continue
        if observed["observed_digest"] != observed["expected_digest"]:
            findings.append(
                _finding(
                    "adapter_output_digest_mismatch",
                    observed["path"],
                    "Observed adapter output digest differs from the declared digest.",
                    "cause_attribution_or_schema_inference",
                )
            )
        if observed["observed_size_bytes"] != observed["expected_size_bytes"]:
            findings.append(
                _finding(
                    "adapter_output_size_mismatch",
                    observed["path"],
                    "Observed adapter output byte size differs from the declared size.",
                    "cause_attribution_or_schema_inference",
                )
            )
    return findings


def _classification(
    adapter_summary: dict[str, Any],
    file_findings: list[dict[str, str]],
) -> str:
    if adapter_summary["classification"] != "adapter_manifest_ready_for_review":
        return "adapter_output_blocked_by_manifest_review"
    if file_findings:
        return "adapter_output_blocked_by_file_findings"
    return "adapter_output_ready_for_review"


def _adapter_manifest_review(adapter_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": adapter_summary["classification"],
        "adapter_id": adapter_summary["adapter"]["adapter_id"],
        "measurement_record_id": adapter_summary["measurement"]["measurement_record_id"],
        "primary_data_path": adapter_summary["primary_data"]["path"],
        "primary_data_format": adapter_summary["primary_data"]["format"],
        "preview_status": adapter_summary["preview"]["status"],
        "declared_row_count": adapter_summary["preview"]["declared_row_count"],
        "linked_context_ids": [item["link_id"] for item in adapter_summary["linked_context"]],
        "adapter_finding_codes": [item["code"] for item in adapter_summary["adapter_findings"]],
        "does_not_claim": "stable_adapter_api_or_schema_inference",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "file_bundle_fixture_transport",
            "severity": "review",
            "basis": "The fixture uses files to pressure the adapter-produced input boundary.",
            "does_not_claim": "final_drop_folder_or_public_adapter_api",
        },
        {
            "code": "writer_like_api_not_decided",
            "severity": "review",
            "basis": "A future writer-like adapter API could supply the same logical facts without the same directory layout.",
            "does_not_claim": "final_transport_or_storage_protocol",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "Scopecat validates adapter output and does not parse the original legacy source format.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "import_not_accepted",
            "severity": "review",
            "basis": "This boundary validates adapter output before any copy/import acceptance step.",
            "does_not_claim": "storage_mutation",
        },
    ]


def validate_adapter_output_boundary(
    adapter_output_root: Path,
    *,
    boundary_manifest: str = _BOUNDARY_MANIFEST,
) -> dict[str, Any]:
    """Validate one adapter-produced output boundary fixture."""
    root = _existing_root(adapter_output_root)
    source = _read_json_file(root, boundary_manifest)
    _validate_boundary_manifest(source)

    observed_files = _observe_declared_files(root, source)
    manifest_observation = next(
        observed for observed in observed_files if observed["role"] == "adapter_manifest"
    )
    manifest_findings = _file_findings([manifest_observation])
    if manifest_findings:
        return {
            "adapter_output_schema": source["adapter_output_schema"],
            "adapter_output_policy": copy.deepcopy(source["adapter_output_policy"]),
            "transport": copy.deepcopy(source["transport"]),
            "classification": "adapter_output_blocked_by_manifest_file_findings",
            "adapter_manifest_path": source["adapter_manifest_path"],
            "adapter_manifest_review": None,
            "observed_files": observed_files,
            "observed_linked_context_refs": [],
            "review_findings": manifest_findings,
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "attention": _attention(),
        }

    adapter_manifest = _read_json_file(root, source["adapter_manifest_path"])
    adapter_summary = build_adapter_authored_legacy_import_summary(adapter_manifest)
    observed_refs = _observe_linked_context_refs(root, source)
    findings = _file_findings(observed_files + observed_refs)
    primary_data_path = adapter_summary["primary_data"]["path"]
    declared_primary_data_path = _declared_file_path_by_role(source, "normalized_primary_data")
    if declared_primary_data_path != primary_data_path:
        findings.append(
            _finding(
                "adapter_output_primary_data_not_declared",
                declared_primary_data_path,
                "The declared normalized primary-data file does not match the adapter manifest.",
                "schema_inference_or_reference_repair",
            )
        )
    available_linked_context_ids = {
        item["link_id"]
        for item in adapter_summary["linked_context"]
        if item["reference_state"] == "adapter_declared_available"
    }
    boundary_linked_context_ids = {ref["link_id"] for ref in source["linked_context_refs"]}
    for ref in source["linked_context_refs"]:
        if ref["link_id"] not in available_linked_context_ids:
            findings.append(
                _finding(
                    "adapter_output_linked_context_not_declared",
                    ref["link_id"],
                    "A linked-context output file does not match an available adapter manifest link.",
                    "recursive_context_import",
                )
            )
    for missing_link_id in sorted(available_linked_context_ids - boundary_linked_context_ids):
        findings.append(
            _finding(
                "adapter_output_linked_context_ref_missing",
                missing_link_id,
                "An available adapter manifest linked context has no declared output file.",
                "recursive_context_import",
            )
        )

    return {
        "adapter_output_schema": source["adapter_output_schema"],
        "adapter_output_policy": copy.deepcopy(source["adapter_output_policy"]),
        "transport": copy.deepcopy(source["transport"]),
        "classification": _classification(adapter_summary, findings),
        "adapter_manifest_path": source["adapter_manifest_path"],
        "adapter_manifest_review": _adapter_manifest_review(adapter_summary),
        "measurement": adapter_summary["measurement"],
        "source_identity": adapter_summary["source_identity"],
        "observed_files": observed_files,
        "observed_linked_context_refs": observed_refs,
        "review_findings": findings,
        "storage_mutation": "not_performed",
        "import_acceptance": "not_performed",
        "attention": _attention(),
    }
