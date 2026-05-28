"""Manifest-only preview for route-local handoff package opening."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.handoff.contracts import (
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_manifest_primary_data,
    validate_non_negative_integer,
    validate_package_item_shape,
    validate_primary_bundle_item,
    validate_public_identifier,
    validate_strict_child_path,
    validate_text,
    validate_unique_reference_targets,
)
from scopecat.handoff.package import HandoffFinding

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


@dataclass(frozen=True)
class HandoffManifestPreview:
    """Manifest-derived package classification and review findings."""

    package_id: str
    display_name: str
    created_by: str
    source_export_summary_id: str
    classification: str
    findings: tuple[HandoffFinding, ...]


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["package_preview_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("handoff package preview policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"handoff package preview policy {key} must be {expected}")


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


def _package_contents(source: dict[str, Any]) -> list[dict[str, Any]]:
    contents = []
    for record in source["selected_measurements"]:
        contents.extend(record["default_bundle"])
    contents.extend(source["linked_context"])
    return contents


def _validate_unique_package_paths(source: dict[str, Any]) -> None:
    seen_paths = set()
    for item in _package_contents(source):
        package_path = item.get("package_path")
        if not package_path:
            continue
        if package_path in seen_paths:
            raise ValueError(f"duplicate package_path: {package_path}")
        seen_paths.add(package_path)


def _validate_manifest(source: dict[str, Any]) -> None:
    _validate_policy(source)
    validate_handoff_package_identity(source["package_identity"], display_path="optional")
    _validate_measurements(source)
    _validate_linked_context(source)
    _validate_unique_package_paths(source)


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


def _findings(source: dict[str, Any]) -> tuple[HandoffFinding, ...]:
    findings = []
    for record in source["selected_measurements"]:
        preview = record["declared_preview_metadata"]
        if preview["status"] == "degraded_preview":
            findings.append(
                HandoffFinding(
                    measurement_record_id=record["measurement_record_id"],
                    subject_type="preview_metadata",
                    subject_id=preview["metadata_authority"],
                    severity="review",
                    code=preview["warning_code"],
                    basis=preview["message"],
                    does_not_claim="packaged_data_unreadable_or_invalid",
                )
            )

    for item in source["linked_context"]:
        if item["package_state"] != "packaged":
            findings.append(
                HandoffFinding(
                    measurement_record_id=item["linked_measurement_record_ids"][0],
                    subject_type="linked_context",
                    subject_id=item["link_id"],
                    severity="review",
                    code=f"linked_context_{item['package_state']}",
                    basis=item["reason"],
                    does_not_claim="package_integrity_or_import_acceptance_failure",
                )
            )

    return tuple(findings)


def preview_handoff_manifest(source: dict[str, Any]) -> HandoffManifestPreview:
    """Validate and classify a handoff package manifest without opening files."""

    _validate_manifest(source)
    identity = source["package_identity"]
    return HandoffManifestPreview(
        package_id=identity["package_id"],
        display_name=identity["display_name"],
        created_by=identity["created_by"],
        source_export_summary_id=identity["source_export_summary_id"],
        classification=_package_classification(source),
        findings=_findings(source),
    )
