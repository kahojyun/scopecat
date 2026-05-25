"""Structured summary builder for handoff package contents preview.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not extract archives, read packaged files, validate
checksums, write storage, accept imports, infer schemas, render previews, open
GUIs, or traverse relation graphs.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.contract_primitives import (
    validate_non_negative_integer,
    validate_public_identifier,
    validate_strict_child_path,
    validate_text,
    validate_unique_reference_targets,
)
from implementation_candidates.handoff_package_contracts import (
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_manifest_primary_data,
    validate_package_item_shape,
    validate_primary_bundle_item,
)

_EXPECTED_POLICY = {
    "preview_authority": "scopecat_export_manifest_only",
    "archive_extraction": "not_performed",
    "file_observation": "not_performed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_PREVIEW_STATUSES = {
    "preview_ready",
    "degraded_preview",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["package_preview_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("handoff package preview policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"handoff package preview policy {key} must be {expected}")


def _validate_package_identity(source: dict[str, Any]) -> None:
    validate_handoff_package_identity(source["package_identity"], display_path="optional")


def _validate_preview_metadata(record: dict[str, Any]) -> None:
    preview = record["declared_preview_metadata"]
    record_id = record["measurement_record_id"]
    if preview["metadata_authority"] != MANIFEST_AUTHORITY:
        raise ValueError("preview metadata authority must stay scopecat_export_manifest")
    if preview["status"] not in _PREVIEW_STATUSES:
        raise ValueError(f"measurement {record_id} has unsupported preview status")

    if preview["status"] == "preview_ready":
        validate_handoff_preview_ready_metadata(
            preview,
            primary_path=record["primary_data"]["package_path"],
            owner=f"measurement {record_id} preview",
        )
        return

    if preview["data_shape"] is not None:
        raise ValueError("degraded preview must not carry data_shape")
    if preview["declared_columns"] or preview["plot_candidates"]:
        raise ValueError("degraded preview must not carry declared columns or plot candidates")
    if not preview.get("warning_code") or not preview.get("message"):
        raise ValueError("degraded preview requires warning_code and message")
    validate_public_identifier(
        preview["warning_code"],
        f"measurement {record_id} degraded preview warning_code",
    )
    validate_text(preview["message"], f"measurement {record_id} degraded preview message")


def _validate_measurements(source: dict[str, Any]) -> None:
    if not source["selected_measurements"]:
        raise ValueError("handoff package contents preview requires selected_measurements")

    seen_ids = set()
    seen_package_paths = set()
    for record in source["selected_measurements"]:
        record_id = record["measurement_record_id"]
        validate_public_identifier(record_id, "measurement_record_id")
        if record_id in seen_ids:
            raise ValueError(f"duplicate measurement_record_id: {record_id}")
        seen_ids.add(record_id)
        validate_non_negative_integer(record["legacy_data_id"], "measurement legacy_data_id")
        validate_text(record["label"], "measurement label")
        validate_public_identifier(record["experiment_type"], "measurement experiment_type")
        validate_public_identifier(record["target"], "measurement target")

        validate_manifest_primary_data(
            record["primary_data"],
            measurement_record_id=record_id,
            owner="primary data",
            digest_size="optional",
        )
        if record["primary_data"]["package_state"] != "packaged":
            raise ValueError("selected measurement primary data must be packaged or rejected")
        _validate_preview_metadata(record)

        primary_bundle_count = 0
        for item in record["default_bundle"]:
            if item["kind"] == "primary_data":
                validate_primary_bundle_item(
                    item,
                    measurement_record_id=record_id,
                    primary=record["primary_data"],
                    owner=f"default bundle item {item['item_id']}",
                )
                primary_bundle_count += 1
            else:
                validate_package_item_shape(item, f"default bundle item {item['item_id']}")
            if item["kind"] != "primary_data" and item.get("package_path"):
                validate_strict_child_path(
                    item["package_path"],
                    f"measurements/{record_id}",
                    f"default bundle item {item['item_id']}",
                )
            package_path = item.get("package_path")
            if package_path and package_path in seen_package_paths:
                raise ValueError(f"duplicate package_path: {package_path}")
            if package_path:
                seen_package_paths.add(package_path)
        if primary_bundle_count != 1:
            raise ValueError(
                "selected measurement default bundle must include one primary data item"
            )


def _validate_linked_context(source: dict[str, Any]) -> None:
    selected_ids = {record["measurement_record_id"] for record in source["selected_measurements"]}
    seen_ids = set()
    for item in source["linked_context"]:
        link_id = item["link_id"]
        validate_public_identifier(link_id, "linked context link_id")
        if link_id in seen_ids:
            raise ValueError(f"duplicate link_id: {link_id}")
        seen_ids.add(link_id)
        validate_package_item_shape(item, f"linked context {link_id}")
        if item.get("package_path"):
            validate_strict_child_path(
                item["package_path"],
                "context",
                f"linked context {link_id}",
            )
        validate_unique_reference_targets(
            item["linked_measurement_record_ids"],
            selected_ids=selected_ids,
            owner=f"linked context {link_id}",
        )


def _validate_unique_package_paths(source: dict[str, Any]) -> None:
    seen_paths = set()
    for item in _package_contents(source):
        package_path = item.get("package_path")
        if not package_path:
            continue
        if package_path in seen_paths:
            raise ValueError(f"duplicate package_path: {package_path}")
        seen_paths.add(package_path)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_package_identity(source)
    _validate_measurements(source)
    _validate_linked_context(source)
    _validate_unique_package_paths(source)


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


def _state_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item["package_state"]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _measurement_classification(record: dict[str, Any]) -> str:
    if record["primary_data"]["package_state"] != "packaged":
        return "blocked_pending_package_review"
    if record["declared_preview_metadata"]["status"] != "preview_ready":
        return "needs_preview_metadata_review"
    return "preview_ready_for_opening"


def _measurement_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_record_id": record["measurement_record_id"],
        "legacy_data_id": record["legacy_data_id"],
        "label": record["label"],
        "experiment_type": record["experiment_type"],
        "target": record["target"],
        "primary_data": copy.deepcopy(record["primary_data"]),
        "preview": _preview_summary(record),
        "default_bundle_count": len(record["default_bundle"]),
        "default_bundle_state_counts": _state_counts(record["default_bundle"]),
        "classification": _measurement_classification(record),
        "import_acceptance": "not_accepted",
        "storage_mutation": "not_performed",
    }


def _content_summary(owner_type: str, owner_id: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "item_id": item["item_id"] if owner_type == "selected_measurement" else item["link_id"],
        "kind": item["kind"],
        "label": item["label"],
        "package_path": item.get("package_path"),
        "include_status": item["include_status"],
        "relation": item["relation"],
        "authority": item["authority"],
        "package_state": item["package_state"],
        "reason": item.get("reason"),
    }


def _package_contents(source: dict[str, Any]) -> list[dict[str, Any]]:
    contents = []
    for record in source["selected_measurements"]:
        contents.extend(
            _content_summary("selected_measurement", record["measurement_record_id"], item)
            for item in record["default_bundle"]
        )
    contents.extend(
        _content_summary("linked_context", item["link_id"], item)
        for item in source["linked_context"]
    )
    return contents


def _package_classification(source: dict[str, Any]) -> str:
    if any(
        record["primary_data"]["package_state"] != "packaged"
        for record in source["selected_measurements"]
    ):
        return "blocked_pending_package_review"
    if any(
        record["declared_preview_metadata"]["status"] != "preview_ready"
        for record in source["selected_measurements"]
    ):
        return "needs_review_before_acceptance"
    if any(item["package_state"] != "packaged" for item in source["linked_context"]):
        return "needs_review_before_acceptance"
    return "preview_ready_for_opening"


def _findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for record in source["selected_measurements"]:
        preview = record["declared_preview_metadata"]
        if preview["status"] == "degraded_preview":
            findings.append(
                {
                    "measurement_record_id": record["measurement_record_id"],
                    "subject_type": "preview_metadata",
                    "subject_id": preview["metadata_authority"],
                    "severity": "review",
                    "finding": preview["warning_code"],
                    "basis": preview["message"],
                    "does_not_claim": "packaged_data_unreadable_or_invalid",
                }
            )

    for item in source["linked_context"]:
        if item["package_state"] != "packaged":
            findings.append(
                {
                    "measurement_record_id": item["linked_measurement_record_ids"][0],
                    "subject_type": "linked_context",
                    "subject_id": item["link_id"],
                    "severity": "review",
                    "finding": f"linked_context_{item['package_state']}",
                    "basis": item["reason"],
                    "does_not_claim": "package_integrity_or_import_acceptance_failure",
                }
            )

    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "manifest_only_package_preview",
            "severity": "info",
            "basis": "Handoff package preview uses explicit Scopecat export manifest facts only.",
            "does_not_claim": "observed_package_file_state",
        },
        {
            "code": "archive_not_extracted",
            "severity": "review",
            "basis": "Package paths are declared references, not opened or extracted.",
            "does_not_claim": "archive_contents_verified",
        },
        {
            "code": "import_not_accepted",
            "severity": "review",
            "basis": "Package contents are classified for review before acceptance.",
            "does_not_claim": "record_written_to_storage",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview metadata must be declared by the export manifest.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "recursive_traversal_not_performed",
            "severity": "review",
            "basis": "Package context is summarized only where explicitly listed.",
            "does_not_claim": "complete_relation_graph",
        },
    ]


def build_handoff_package_contents_preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a handoff package contents preview from explicit manifest input."""
    _validate_references(source)
    contents = _package_contents(source)
    package = {
        "package_id": source["package_identity"]["package_id"],
        "display_name": source["package_identity"]["display_name"],
        "created_by": source["package_identity"]["created_by"],
        "source_export_summary_id": source["package_identity"]["source_export_summary_id"],
        "classification": _package_classification(source),
    }
    if "display_path" in source["package_identity"]:
        package["display_path"] = source["package_identity"]["display_path"]
    return {
        "package_preview_policy": copy.deepcopy(source["package_preview_policy"]),
        "package": package,
        "selected_measurements": [
            _measurement_summary(record) for record in source["selected_measurements"]
        ],
        "package_contents": contents,
        "package_content_state_counts": _state_counts(contents),
        "preview_findings": _findings(source),
        "attention": _attention(),
    }
