"""Structured summary builder for adapter-authored legacy import manifests.

This module validates a normalized manifest emitted by an external adapter. It
does not parse legacy measurement formats, read primary data files, write
storage, accept imports, infer schemas, calculate checksums, render previews,
open GUIs, or define a stable public API.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_MANIFEST_SCHEMA = "scopecat.adapter_import_manifest.v0"

_EXPECTED_POLICY = {
    "manifest_authority": "adapter_authored",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "source_observation": "adapter_declared_only",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "package_integrity": "not_claimed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}

_ADAPTER_AUTHORITY = "external_adapter"
_DECLARED_AUTHORITY = "adapter_declared"
_SOURCE_SYSTEM_KIND = "external_legacy_system"
_PRIMARY_DATA_KIND = "primary_data"
_PRIMARY_DATA_FORMATS = {"csv_table"}
_PREVIEW_STATUSES = {"preview_ready", "degraded_preview"}
_REFERENCE_STATES = {"adapter_declared_available", "unavailable", "redacted"}
_FINDING_SEVERITIES = {"info", "review", "block_import"}
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private"))
_PRIVATE_TOKEN_MARKERS = {"users", "private"}


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


def _validate_redacted_display_path(path: str) -> None:
    if (
        not path
        or path.startswith(("/", "~"))
        or "\\" in path
        or re.match(r"^[A-Za-z]:[\\/]", path)
        or any(marker in path for marker in _PRIVATE_PATH_MARKERS)
        or "redacted" not in path.lower()
    ):
        raise ValueError("source original_path_display must be public-safe and redacted")


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
    policy = source["adapter_import_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("adapter import policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"adapter import policy {key} must be {expected}")


def _validate_adapter(source: dict[str, Any]) -> None:
    adapter = source["adapter"]
    if adapter["parsing_authority"] != _ADAPTER_AUTHORITY:
        raise ValueError("legacy parsing authority must stay external_adapter")
    if adapter["source_system_kind"] != _SOURCE_SYSTEM_KIND:
        raise ValueError("source system kind must stay external_legacy_system")


def _validate_source_identity(source_identity: dict[str, Any]) -> None:
    if source_identity["local_path_redacted"] is not True:
        raise ValueError("legacy source local path must stay redacted")
    _validate_public_safe_token(
        source_identity["external_record_id"],
        "source external_record_id",
        requires_redacted=False,
    )
    _validate_public_safe_token(
        source_identity["external_root_label"],
        "source external_root_label",
        requires_redacted=True,
    )
    _validate_redacted_display_path(source_identity["original_path_display"])


def _validate_primary_data(source: dict[str, Any]) -> None:
    primary_data = source["primary_data"]
    _validate_relative_path(primary_data["path"], "primary data")
    if primary_data["authority"] != _DECLARED_AUTHORITY:
        raise ValueError("primary data authority must stay adapter_declared")
    if primary_data["kind"] != _PRIMARY_DATA_KIND:
        raise ValueError("primary data kind must stay primary_data")
    if primary_data["format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("primary data format is unsupported")
    if primary_data["reference_state"] not in _REFERENCE_STATES:
        raise ValueError("primary data reference_state is unsupported")
    if primary_data["reference_state"] != "adapter_declared_available" and not primary_data.get(
        "reason"
    ):
        raise ValueError("unavailable or redacted primary data requires reason")
    if primary_data["reference_state"] == "adapter_declared_available" and primary_data.get(
        "reason"
    ):
        raise ValueError("available primary data must not carry reason")


def _validate_preview_metadata(source: dict[str, Any]) -> None:
    preview = source["declared_preview_metadata"]
    primary_data = source["primary_data"]

    if preview["metadata_authority"] != _DECLARED_AUTHORITY:
        raise ValueError("preview metadata authority must stay adapter_declared")
    if preview["status"] not in _PREVIEW_STATUSES:
        raise ValueError("unsupported preview metadata status")

    if preview["status"] == "preview_ready":
        if preview["data_shape"] is None:
            raise ValueError("preview-ready metadata requires data_shape")
        if not isinstance(preview["declared_row_count"], int) or preview["declared_row_count"] <= 0:
            raise ValueError("preview-ready metadata requires positive declared_row_count")
        declared_columns = preview["declared_columns"]
        declared_names = {column["name"] for column in declared_columns}
        if len(declared_names) != len(declared_columns):
            raise ValueError("declared preview columns must have unique names")
        axis_order = preview["data_shape"]["axis_order"]
        if not declared_names or not axis_order:
            raise ValueError("preview-ready metadata requires declared columns and axis order")
        if any(axis not in declared_names for axis in axis_order):
            raise ValueError("preview axis order must reference declared columns")
        for candidate in preview["plot_candidates"]:
            if candidate["source"] != primary_data["path"]:
                raise ValueError("plot candidate source must match primary data path")
            if candidate["x"] not in declared_names or candidate["y"] not in declared_names:
                raise ValueError("plot candidate axes must reference declared columns")
        return

    if preview["data_shape"] is not None:
        raise ValueError("degraded preview must not carry data_shape")
    if preview["declared_columns"] or preview["plot_candidates"]:
        raise ValueError("degraded preview must not carry declared columns or plot candidates")
    if not preview.get("warning_code") or not preview.get("message"):
        raise ValueError("degraded preview requires warning_code and message")


def _validate_linked_context(source: dict[str, Any]) -> None:
    seen = set()
    for item in source["linked_context"]:
        link_id = item["link_id"]
        if link_id in seen:
            raise ValueError(f"duplicate link_id: {link_id}")
        seen.add(link_id)
        if item["authority"] != _DECLARED_AUTHORITY:
            raise ValueError(f"linked context {link_id} authority must stay adapter_declared")
        if item["reference_state"] not in _REFERENCE_STATES:
            raise ValueError(f"linked context {link_id} reference_state is unsupported")
        if item["reference_state"] in {"unavailable", "redacted"} and not item.get("reason"):
            raise ValueError(f"linked context {link_id} requires reason")
        if item["reference_state"] == "adapter_declared_available" and item.get("reason"):
            raise ValueError(f"linked context {link_id} must not carry reason")


def _validate_adapter_findings(source: dict[str, Any]) -> None:
    seen = set()
    for finding in source["adapter_findings"]:
        code = finding["code"]
        if code in seen:
            raise ValueError(f"duplicate adapter finding code: {code}")
        seen.add(code)
        if finding["severity"] not in _FINDING_SEVERITIES:
            raise ValueError(f"adapter finding {code} severity is unsupported")
        if not finding["message"]:
            raise ValueError(f"adapter finding {code} requires message")


def _validate_references(source: dict[str, Any]) -> None:
    if source["manifest_schema"] != _MANIFEST_SCHEMA:
        raise ValueError(f"manifest_schema must be {_MANIFEST_SCHEMA}")
    _validate_policy(source)
    _validate_adapter(source)
    _validate_source_identity(source["source_identity"])
    _validate_primary_data(source)
    _validate_preview_metadata(source)
    _validate_linked_context(source)
    _validate_adapter_findings(source)


def _preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    preview = source["declared_preview_metadata"]
    if preview["status"] == "preview_ready":
        return {
            "status": "preview_ready",
            "metadata_authority": preview["metadata_authority"],
            "shape_kind": preview["data_shape"]["kind"],
            "axis_order": list(preview["data_shape"]["axis_order"]),
            "declared_row_count": preview["declared_row_count"],
            "declared_roles": copy.deepcopy(preview["declared_columns"]),
            "plot_candidates": [
                {
                    "x": candidate["x"],
                    "y": candidate["y"],
                    "source": candidate["source"],
                }
                for candidate in preview["plot_candidates"]
            ],
            "warnings": [],
        }

    return {
        "status": "degraded_preview",
        "metadata_authority": preview["metadata_authority"],
        "shape_kind": None,
        "axis_order": [],
        "declared_row_count": None,
        "declared_roles": [],
        "plot_candidates": [],
        "warnings": [
            {
                "code": preview["warning_code"],
                "message": preview["message"],
            }
        ],
    }


def _classification(source: dict[str, Any]) -> str:
    if source["primary_data"]["reference_state"] != "adapter_declared_available":
        return "blocked_pending_source_review"
    if any(item["severity"] == "block_import" for item in source["adapter_findings"]):
        return "blocked_by_adapter_finding"
    if source["declared_preview_metadata"]["status"] != "preview_ready":
        return "needs_preview_metadata_review"
    if any(
        item["reference_state"] != "adapter_declared_available" for item in source["linked_context"]
    ):
        return "needs_linked_context_review"
    return "adapter_manifest_ready_for_review"


def _adapter_summary(source: dict[str, Any]) -> dict[str, Any]:
    adapter = source["adapter"]
    return {
        "adapter_id": adapter["adapter_id"],
        "name": adapter["name"],
        "version": adapter["version"],
        "source_system_kind": adapter["source_system_kind"],
        "source_system_detail": adapter["source_system_detail"],
        "parsing_authority": adapter["parsing_authority"],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "adapter_manifest_boundary",
            "severity": "info",
            "basis": "Scopecat consumes normalized adapter-authored facts only.",
            "does_not_claim": "stable_public_sdk_or_cli",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "Legacy source parsing is performed by an external adapter before Scopecat sees the manifest.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "source_observation_adapter_declared",
            "severity": "review",
            "basis": "Primary data and source identity state are adapter-declared; Scopecat does not inspect legacy source files in this candidate.",
            "does_not_claim": "file_contents_or_checksum_verified",
        },
        {
            "code": "import_not_accepted",
            "severity": "review",
            "basis": "The manifest is summarized for review before acceptance.",
            "does_not_claim": "record_written_to_storage",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview metadata must be declared by the adapter-authored manifest.",
            "does_not_claim": "automatic_legacy_schema_detection",
        },
    ]


def build_adapter_authored_legacy_import_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from a normalized adapter-authored manifest."""
    _validate_references(source)
    return {
        "manifest_schema": source["manifest_schema"],
        "adapter_import_policy": copy.deepcopy(source["adapter_import_policy"]),
        "adapter": _adapter_summary(source),
        "measurement": copy.deepcopy(source["measurement"]),
        "source_identity": copy.deepcopy(source["source_identity"]),
        "primary_data": copy.deepcopy(source["primary_data"]),
        "preview": _preview_summary(source),
        "linked_context": copy.deepcopy(source["linked_context"]),
        "adapter_findings": copy.deepcopy(source["adapter_findings"]),
        "classification": _classification(source),
        "import_acceptance": "not_accepted",
        "storage_mutation": "not_performed",
        "attention": _attention(),
    }
