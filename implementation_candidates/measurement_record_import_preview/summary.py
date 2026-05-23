"""Structured summary builder for measurement record import preview.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source data, copy files, write storage,
accept imports, infer schemas, calculate checksums, render previews, open GUIs,
or traverse relation graphs.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "preview_authority": "explicit_manifest_only",
    "source_observation": "not_performed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "package_integrity": "not_claimed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_REFERENCE_STATES = {
    "declared_available",
    "unavailable",
    "moved",
}

_PREVIEW_STATUSES = {
    "preview_ready",
    "degraded_preview",
}

_LINK_STATES = {
    "declared_available",
    "unavailable",
    "redacted",
}

_MANIFEST_AUTHORITY = "incoming_manifest"
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private"))


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


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


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["import_preview_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("import preview policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"import preview policy {key} must be {expected}")


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
        raise ValueError("incoming source display path must be public-safe and redacted")


def _validate_reference_state(state: str, owner: str) -> None:
    if state not in _REFERENCE_STATES:
        raise ValueError(f"{owner} has unsupported reference_state: {state}")


def _validate_link_state(state: str, owner: str) -> None:
    if state not in _LINK_STATES:
        raise ValueError(f"{owner} has unsupported link_state: {state}")


def _validate_preview_metadata(record: dict[str, Any]) -> None:
    preview = record["declared_preview_metadata"]
    if preview["metadata_authority"] != _MANIFEST_AUTHORITY:
        raise ValueError("preview metadata authority must stay incoming_manifest")
    if preview["status"] not in _PREVIEW_STATUSES:
        raise ValueError(
            f"incoming record {record['incoming_record_id']} has unsupported preview status"
        )

    if preview["status"] == "preview_ready":
        if preview["data_shape"] is None:
            raise ValueError("preview-ready metadata requires data_shape")
        declared_names = {column["name"] for column in preview["declared_columns"]}
        axis_order = preview["data_shape"]["axis_order"]
        if not declared_names or not axis_order:
            raise ValueError("preview-ready metadata requires declared columns and axis order")
        if any(axis not in declared_names for axis in axis_order):
            raise ValueError("preview axis order must reference declared columns")
        for candidate in preview["plot_candidates"]:
            if candidate["source"] != record["primary_data"]["path"]:
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


def _validate_linked_context(record: dict[str, Any]) -> None:
    seen = set()
    for item in record["linked_context"]:
        link_id = item["link_id"]
        if link_id in seen:
            raise ValueError(f"duplicate link_id: {link_id}")
        seen.add(link_id)
        _validate_relative_path(item["path"], f"linked context {link_id}")
        _validate_link_state(item["link_state"], f"linked context {link_id}")
        if item["authority"] != _MANIFEST_AUTHORITY:
            raise ValueError(f"linked context {link_id} authority must stay incoming_manifest")
        if item["link_state"] in {"unavailable", "redacted"} and not item.get("reason"):
            raise ValueError(f"linked context {link_id} requires reason")
        if item["link_state"] == "declared_available" and item.get("reason"):
            raise ValueError(f"linked context {link_id} must not carry reason")


def _validate_record(record: dict[str, Any]) -> None:
    source_identity = record["source_identity"]
    if source_identity["local_path_redacted"] is not True:
        raise ValueError("incoming source local path must stay redacted")
    _validate_redacted_display_path(source_identity["display_path"])

    _validate_relative_path(record["current_reference"]["path"], "current reference")
    _validate_reference_state(
        record["current_reference"]["reference_state"],
        f"incoming record {record['incoming_record_id']}",
    )
    if record["current_reference"]["reference_state"] in {"unavailable", "moved"} and not record[
        "current_reference"
    ].get("reason"):
        raise ValueError("unavailable or moved current reference requires reason")

    primary_data = record["primary_data"]
    _validate_relative_path(primary_data["path"], "primary data")
    if primary_data["path"] != record["current_reference"]["path"]:
        raise ValueError("primary data path must match current reference path")
    if primary_data["authority"] != _MANIFEST_AUTHORITY:
        raise ValueError("primary data authority must stay incoming_manifest")

    _validate_preview_metadata(record)
    _validate_linked_context(record)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _records_by_key(source["incoming_records"], "incoming_record_id")
    for record in source["incoming_records"]:
        _validate_record(record)


def _preview_summary(record: dict[str, Any]) -> dict[str, Any]:
    preview = record["declared_preview_metadata"]
    if preview["status"] == "preview_ready":
        return {
            "status": "preview_ready",
            "metadata_authority": preview["metadata_authority"],
            "shape_kind": preview["data_shape"]["kind"],
            "axis_order": list(preview["data_shape"]["axis_order"]),
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
        "declared_roles": [],
        "plot_candidates": [],
        "warnings": [
            {
                "code": preview["warning_code"],
                "message": preview["message"],
            }
        ],
    }


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _record_classification(record: dict[str, Any]) -> str:
    if record["current_reference"]["reference_state"] != "declared_available":
        return "blocked_pending_source_review"
    if record["declared_preview_metadata"]["status"] != "preview_ready":
        return "needs_preview_metadata_review"
    if any(item["link_state"] != "declared_available" for item in record["linked_context"]):
        return "needs_linked_context_review"
    return "preview_ready_for_review"


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "incoming_record_id": record["incoming_record_id"],
        "label": record["label"],
        "source_kind": record["source_identity"]["kind"],
        "source_label": record["source_identity"]["label"],
        "display_path": record["source_identity"]["display_path"],
        "current_reference": copy.deepcopy(record["current_reference"]),
        "primary_data": copy.deepcopy(record["primary_data"]),
        "preview": _preview_summary(record),
        "linked_context_count": len(record["linked_context"]),
        "linked_context_state_counts": _state_counts(record["linked_context"], "link_state"),
        "classification": _record_classification(record),
        "import_acceptance": "not_accepted",
        "storage_mutation": "not_performed",
    }


def _linked_context_summary(record: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "incoming_record_id": record["incoming_record_id"],
        "link_id": item["link_id"],
        "kind": item["kind"],
        "label": item["label"],
        "path": item["path"],
        "relation": item["relation"],
        "authority": item["authority"],
        "link_state": item["link_state"],
        "reason": item.get("reason"),
    }


def _findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for record in source["incoming_records"]:
        record_id = record["incoming_record_id"]
        reference = record["current_reference"]
        preview = record["declared_preview_metadata"]

        if reference["reference_state"] != "declared_available":
            findings.append(
                {
                    "incoming_record_id": record_id,
                    "subject_type": "primary_data",
                    "subject_id": reference["path"],
                    "severity": "block_preview",
                    "finding": f"source_{reference['reference_state']}",
                    "basis": reference["reason"],
                    "does_not_claim": "source_permanently_missing_or_invalid",
                }
            )

        if preview["status"] == "degraded_preview":
            findings.append(
                {
                    "incoming_record_id": record_id,
                    "subject_type": "preview_metadata",
                    "subject_id": preview["metadata_authority"],
                    "severity": "review",
                    "finding": preview["warning_code"],
                    "basis": preview["message"],
                    "does_not_claim": "record_cannot_be_imported_or_plotted_later",
                }
            )

        for item in record["linked_context"]:
            if item["link_state"] != "declared_available":
                findings.append(
                    {
                        "incoming_record_id": record_id,
                        "subject_type": "linked_context",
                        "subject_id": item["link_id"],
                        "severity": "review",
                        "finding": f"linked_context_{item['link_state']}",
                        "basis": item["reason"],
                        "does_not_claim": "relation_graph_or_import_package_invalid",
                    }
                )

    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "manifest_only_preview",
            "severity": "info",
            "basis": "Import preview uses explicit incoming-record manifest facts only.",
            "does_not_claim": "observed_source_file_state",
        },
        {
            "code": "source_data_not_read",
            "severity": "review",
            "basis": "Primary data paths are declared references, not opened or parsed.",
            "does_not_claim": "file_contents_verified",
        },
        {
            "code": "import_not_accepted",
            "severity": "review",
            "basis": "Incoming records are classified for review before acceptance.",
            "does_not_claim": "record_written_to_storage",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview metadata must be declared by the incoming manifest.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "recursive_traversal_not_performed",
            "severity": "review",
            "basis": "Linked context is summarized only where explicitly listed.",
            "does_not_claim": "complete_relation_graph",
        },
    ]


def build_measurement_record_import_preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured import-preview summary from explicit manifest input."""
    _validate_references(source)
    return {
        "import_preview_policy": copy.deepcopy(source["import_preview_policy"]),
        "incoming_records": [_record_summary(record) for record in source["incoming_records"]],
        "linked_context": [
            _linked_context_summary(record, item)
            for record in source["incoming_records"]
            for item in record["linked_context"]
        ],
        "preview_findings": _findings(source),
        "attention": _attention(),
    }
