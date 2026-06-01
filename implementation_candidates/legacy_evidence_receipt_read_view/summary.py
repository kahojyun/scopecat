"""Read view for appended legacy sidecar review-evidence receipts.

This module reads an existing measurement-record manifest plus explicitly
declared review-evidence receipt paths. It does not scan storage, read primary
data, import legacy payloads, parse legacy primary data, verify previews, repair
references, write storage, decide measurement validity, or define GUI behavior.
"""

from __future__ import annotations

import copy
import hashlib
import json
from json import JSONDecodeError
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
)

_READ_SCHEMA = "scopecat.legacy_evidence_receipt_read_view.v0"

_EXPECTED_POLICY = {
    "read_authority": "explicit_legacy_evidence_receipt_read_view",
    "source_authority": "caller_provided_storage_root_plus_declared_paths",
    "read_behavior": "read_existing_manifest_and_declared_review_evidence_receipts",
    "storage_scan": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_read": "not_performed",
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
    "shared_read_schema": "not_defined",
}

_REQUEST_FIELDS = {
    "request_id",
    "measurement_id",
    "record_dir",
    "manifest_path",
    "receipt_paths",
}

_RECEIPT_EFFECT_EXPECTATIONS = {
    "manifest_update": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "preview_verification": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_RECEIPT_REQUIRED_FIELDS = {
    "receipt_id",
    "write_request_id",
    "measurement_id",
    "append_intent_request_id",
    "approved_at",
    "operator_role",
    "source_review",
    "planned_review_evidence",
    "review_finding_count",
    "review_findings",
    "receipt_effects",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["evidence_receipt_read_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy evidence receipt read policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy evidence receipt read policy {key} must be {expected}")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["read_request"]
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("legacy evidence receipt read request must match expected shape")
    validate_public_identifier(request["request_id"], "read request_id")
    validate_public_identifier(request["measurement_id"], "read measurement_id")
    validate_relative_path(request["record_dir"], "read request record_dir")
    validate_relative_path(request["manifest_path"], "read request manifest_path")
    validate_strict_child_path(
        request["manifest_path"], request["record_dir"], "read request manifest_path"
    )
    receipt_paths = request["receipt_paths"]
    if not isinstance(receipt_paths, list) or not receipt_paths:
        raise ValueError("read request receipt_paths must be a non-empty list")
    if len(set(receipt_paths)) != len(receipt_paths):
        raise ValueError("read request receipt_paths must be unique")
    for path in receipt_paths:
        validate_relative_path(path, "read request receipt_path")
        validate_strict_child_path(path, request["record_dir"], "read request receipt_path")


def _validate_source(source: dict[str, Any]) -> None:
    if source["evidence_receipt_read_schema"] != _READ_SCHEMA:
        raise ValueError(f"evidence_receipt_read_schema must be {_READ_SCHEMA}")
    _validate_policy(source)
    _validate_request(source)


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _finding(code: str, basis: str, *, receipt_path: str | None = None) -> dict[str, str]:
    item = {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": "repair_import_or_validity_decision",
    }
    if receipt_path is not None:
        item["receipt_path"] = receipt_path
    return item


def _ensure_record_dir(request: dict[str, Any], storage_root: Path) -> None:
    ensure_no_symlink_parents(
        storage_root, request["record_dir"], "legacy evidence read record_dir"
    )
    target = path_under(storage_root, request["record_dir"])
    if target.is_symlink():
        raise ValueError("legacy evidence read record directory is a symlink")
    if not target.is_dir():
        raise ValueError("legacy evidence read record directory is unavailable")


def _read_manifest(request: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    _ensure_record_dir(request, storage_root)
    ensure_no_symlink_parents(
        storage_root, request["manifest_path"], "legacy evidence read manifest"
    )
    manifest_path = path_under(storage_root, request["manifest_path"])
    if manifest_path.is_symlink():
        raise ValueError("legacy evidence read manifest target is a symlink")
    if not manifest_path.is_file():
        raise ValueError("legacy evidence read manifest file is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["measurement_record_id"] != request["measurement_id"]:
        raise ValueError("legacy evidence read manifest id must match request")
    if manifest["record_dir"] != request["record_dir"]:
        raise ValueError("legacy evidence read manifest record_dir must match request")
    return {
        "measurement_record_id": manifest["measurement_record_id"],
        "record_dir": manifest["record_dir"],
        "manifest_path": request["manifest_path"],
        "manifest_state": "matched_existing_record",
    }


def _read_receipt_file(path: str, storage_root: Path) -> tuple[bytes | None, dict[str, Any] | None]:
    ensure_no_symlink_parents(storage_root, path, "legacy evidence receipt")
    target = path_under(storage_root, path)
    if target.is_symlink():
        raise ValueError("legacy evidence receipt target is a symlink")
    if not target.is_file():
        return None, None
    content = target.read_bytes()
    try:
        return content, json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError):
        return content, None


def _receipt_effect_findings(receipt: dict[str, Any], path: str) -> list[dict[str, str]]:
    findings = []
    effects = receipt.get("receipt_effects")
    if not isinstance(effects, dict):
        return [
            _finding(
                "legacy_evidence_receipt_effects_missing",
                "Receipt does not carry receipt_effects.",
                receipt_path=path,
            )
        ]
    for key, expected in _RECEIPT_EFFECT_EXPECTATIONS.items():
        if effects.get(key) != expected:
            findings.append(
                _finding(
                    "legacy_evidence_receipt_effect_claim",
                    f"Receipt effect {key} must be {expected}.",
                    receipt_path=path,
                )
            )
    return findings


def _validate_receipt_shape(
    receipt: dict[str, Any], path: str, measurement_id: str
) -> list[dict[str, str]]:
    findings = []
    if set(receipt) != _RECEIPT_REQUIRED_FIELDS:
        findings.append(
            _finding(
                "legacy_evidence_receipt_shape_mismatch",
                "Receipt fields do not match the expected review-evidence receipt shape.",
                receipt_path=path,
            )
        )
        return findings
    if receipt["measurement_id"] != measurement_id:
        findings.append(
            _finding(
                "legacy_evidence_receipt_measurement_mismatch",
                "Receipt measurement_id does not match the requested record.",
                receipt_path=path,
            )
        )
    if receipt["review_finding_count"] != len(receipt["review_findings"]):
        findings.append(
            _finding(
                "legacy_evidence_receipt_finding_count_mismatch",
                "Receipt review_finding_count does not match review_findings.",
                receipt_path=path,
            )
        )
    findings.extend(_receipt_effect_findings(receipt, path))
    return findings


def _receipt_summary(
    path: str, request: dict[str, Any], storage_root: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    content, receipt = _read_receipt_file(path, storage_root)
    if content is None:
        return (
            {
                "receipt_path": path,
                "status": "unavailable",
                "digest": None,
                "size_bytes": None,
            },
            [
                _finding(
                    "legacy_evidence_receipt_unavailable",
                    "Declared review-evidence receipt path is unavailable.",
                    receipt_path=path,
                )
            ],
        )
    if receipt is None:
        return (
            {
                "receipt_path": path,
                "status": "malformed",
                "digest": _sha256_bytes(content),
                "size_bytes": len(content),
            },
            [
                _finding(
                    "legacy_evidence_receipt_malformed",
                    "Declared review-evidence receipt is not valid UTF-8 JSON.",
                    receipt_path=path,
                )
            ],
        )

    findings = _validate_receipt_shape(receipt, path, request["measurement_id"])
    status = "observed" if not findings else "observed_with_findings"
    return (
        {
            "receipt_path": path,
            "status": status,
            "digest": _sha256_bytes(content),
            "size_bytes": len(content),
            "receipt_id": receipt.get("receipt_id"),
            "append_intent_request_id": receipt.get("append_intent_request_id"),
            "source_review": copy.deepcopy(receipt.get("source_review")),
            "planned_review_evidence": copy.deepcopy(receipt.get("planned_review_evidence")),
            "review_finding_count": receipt.get("review_finding_count"),
            "receipt_effects": copy.deepcopy(receipt.get("receipt_effects")),
        },
        findings,
    )


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(findings: list[dict[str, str]]) -> str:
    if findings:
        return "legacy_evidence_receipt_read_view_needs_review"
    return "legacy_evidence_receipt_read_view_ready"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "receipt_read_view_only",
            "severity": "info",
            "basis": "The view reads declared review-evidence receipt paths under an existing record.",
            "does_not_claim": "storage_scan_or_read_model_refresh",
        },
        {
            "code": "primary_data_not_read",
            "severity": "review",
            "basis": "The view does not open primary data or legacy payloads.",
            "does_not_claim": "primary_data_import_or_legacy_payload_validation",
        },
        {
            "code": "reference_repair_not_performed",
            "severity": "review",
            "basis": "Missing or malformed receipts become review findings.",
            "does_not_claim": "moved_reference_discovery_or_repair",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "Receipt visibility does not decide measurement validity.",
            "does_not_claim": "measurement_validity",
        },
    ]


def read_legacy_evidence_receipts(source: dict[str, Any], *, storage_root: Path) -> dict[str, Any]:
    """Build a read-only view over declared legacy review-evidence receipts."""
    _validate_source(source)
    storage_root_resolved = existing_directory_root(
        storage_root, "legacy evidence receipt read storage"
    )
    request = source["read_request"]
    record = _read_manifest(request, storage_root_resolved)

    receipts = []
    findings = []
    for path in request["receipt_paths"]:
        receipt, receipt_findings = _receipt_summary(path, request, storage_root_resolved)
        receipts.append(receipt)
        findings.extend(receipt_findings)

    return {
        "evidence_receipt_read_schema": source["evidence_receipt_read_schema"],
        "evidence_receipt_read_policy": copy.deepcopy(source["evidence_receipt_read_policy"]),
        "classification": _classification(findings),
        "record": record,
        "read_request": copy.deepcopy(request),
        "receipt_view": {
            "requested_receipt_count": len(request["receipt_paths"]),
            "observed_receipt_count": sum(
                1 for receipt in receipts if receipt["status"].startswith("observed")
            ),
            "status_counts": _state_counts(receipts, "status"),
            "receipts": receipts,
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "read_effects": {
            "storage_scan": "not_performed",
            "storage_mutation": "not_performed",
            "record_write": "not_performed",
            "primary_data_read": "not_performed",
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
        },
        "attention": _attention(),
    }
