"""Route-private manifest preview for handoff package opening."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import (
    MANIFEST_AUTHORITY,
    validate_context_reference,
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

_PREVIEW_STATUSES = {
    "preview_ready",
    "degraded_preview",
}


@dataclass(frozen=True)
class HandoffManifestIdentity:
    """Validated identity facts declared by a handoff package manifest."""

    package_id: str
    display_name: str
    created_by: str
    source_export_summary_id: str


@dataclass(frozen=True)
class HandoffManifestPrimaryData:
    """Validated primary-data declaration for one selected measurement."""

    package_path: str
    format: str
    digest: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, init=False)
class HandoffManifestPreviewMetadata:
    """Validated declared table-preview metadata for one selected measurement."""

    status: str
    metadata_authority: str
    _declared_columns: tuple[dict[str, str], ...]
    warning_code: str | None = None
    message: str | None = None

    def __init__(
        self,
        *,
        status: str,
        metadata_authority: str,
        declared_columns: tuple[dict[str, str], ...],
        warning_code: str | None = None,
        message: str | None = None,
    ) -> None:
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "metadata_authority", metadata_authority)
        object.__setattr__(
            self,
            "_declared_columns",
            tuple(copy.deepcopy(column) for column in declared_columns),
        )
        object.__setattr__(self, "warning_code", warning_code)
        object.__setattr__(self, "message", message)

    @property
    def declared_columns(self) -> tuple[dict[str, str], ...]:
        return tuple(copy.deepcopy(column) for column in self._declared_columns)

    @property
    def declared_column_names(self) -> tuple[str, ...]:
        return tuple(column["name"] for column in self._declared_columns)


@dataclass(frozen=True)
class HandoffManifestMeasurement:
    """Validated manifest declaration for one selected measurement."""

    measurement_record_id: str
    legacy_data_id: int
    label: str
    experiment_type: str
    target: str
    primary_data: HandoffManifestPrimaryData
    preview_metadata: HandoffManifestPreviewMetadata


@dataclass(frozen=True)
class HandoffManifestLinkedContext:
    """Validated linked-context manifest reference."""

    link_id: str
    kind: str
    label: str
    package_path: str | None
    package_state: str
    reason: str | None
    linked_measurement_record_ids: tuple[str, ...]
    digest: str | None = None
    size_bytes: int | None = None
    context_reference: dict[str, str] | None = None


@dataclass(frozen=True)
class HandoffManifestPreview:
    """Validated manifest-derived state used by read-only package opening."""

    identity: HandoffManifestIdentity
    classification: str
    measurements: tuple[HandoffManifestMeasurement, ...]
    linked_context: tuple[HandoffManifestLinkedContext, ...]
    findings: tuple[HandoffFinding, ...]

    @property
    def package_id(self) -> str:
        return self.identity.package_id

    @property
    def display_name(self) -> str:
        return self.identity.display_name

    @property
    def created_by(self) -> str:
        return self.identity.created_by

    @property
    def source_export_summary_id(self) -> str:
        return self.identity.source_export_summary_id


def _identity_from_manifest(source: dict[str, Any]) -> HandoffManifestIdentity:
    identity = source["package_identity"]
    return HandoffManifestIdentity(
        package_id=identity["package_id"],
        display_name=identity["display_name"],
        created_by=identity["created_by"],
        source_export_summary_id=identity["source_export_summary_id"],
    )


def _primary_data_from_record(record: dict[str, Any]) -> HandoffManifestPrimaryData:
    primary = record["primary_data"]
    return HandoffManifestPrimaryData(
        package_path=primary["package_path"],
        format=primary["format"],
        digest=primary.get("digest"),
        size_bytes=primary.get("size_bytes"),
    )


def _preview_metadata_from_record(record: dict[str, Any]) -> HandoffManifestPreviewMetadata:
    preview = record["declared_preview_metadata"]
    return HandoffManifestPreviewMetadata(
        status=preview["status"],
        metadata_authority=preview["metadata_authority"],
        declared_columns=tuple(preview["declared_columns"]),
        warning_code=preview.get("warning_code"),
        message=preview.get("message"),
    )


def _measurements_from_manifest(source: dict[str, Any]) -> tuple[HandoffManifestMeasurement, ...]:
    return tuple(
        HandoffManifestMeasurement(
            measurement_record_id=record["measurement_record_id"],
            legacy_data_id=record["legacy_data_id"],
            label=record["label"],
            experiment_type=record["experiment_type"],
            target=record["target"],
            primary_data=_primary_data_from_record(record),
            preview_metadata=_preview_metadata_from_record(record),
        )
        for record in source["selected_measurements"]
    )


def _linked_context_from_manifest(
    source: dict[str, Any],
) -> tuple[HandoffManifestLinkedContext, ...]:
    return tuple(
        HandoffManifestLinkedContext(
            link_id=item["link_id"],
            kind=item["kind"],
            label=item["label"],
            package_path=item.get("package_path"),
            package_state=item["package_state"],
            reason=item["reason"],
            linked_measurement_record_ids=tuple(item["linked_measurement_record_ids"]),
            digest=item.get("digest"),
            size_bytes=item.get("size_bytes"),
            context_reference=copy.deepcopy(item.get("context_reference")),
        )
        for item in source["linked_context"]
    )


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

    if preview["declared_columns"]:
        raise ValueError("degraded preview must not carry declared columns")
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
        _validate_context_reference(item)


def _validate_context_reference(item: dict[str, Any]) -> None:
    reference = item.get("context_reference")
    if reference is None:
        return
    validate_context_reference(
        reference,
        item_kind=item["kind"],
        owner="linked context",
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
    validate_handoff_package_identity(source["package_identity"], display_path="optional")
    _validate_measurements(source)
    _validate_linked_context(source)
    _validate_unique_package_paths(source)


def _package_classification(
    *,
    measurements: tuple[HandoffManifestMeasurement, ...],
    linked_context: tuple[HandoffManifestLinkedContext, ...],
) -> str:
    if any(measurement.preview_metadata.status != "preview_ready" for measurement in measurements):
        return "needs_review_before_acceptance"
    if any(item.package_state != "packaged" for item in linked_context):
        return "needs_review_before_acceptance"
    return "preview_ready_for_opening"


def _findings(
    *,
    measurements: tuple[HandoffManifestMeasurement, ...],
    linked_context: tuple[HandoffManifestLinkedContext, ...],
) -> tuple[HandoffFinding, ...]:
    findings = []
    for measurement in measurements:
        preview = measurement.preview_metadata
        if preview.status == "degraded_preview":
            if preview.warning_code is None or preview.message is None:
                raise ValueError("degraded preview requires warning_code and message")
            findings.append(
                HandoffFinding(
                    measurement_record_id=measurement.measurement_record_id,
                    subject_type="preview_metadata",
                    subject_id=preview.metadata_authority,
                    severity="review",
                    code=preview.warning_code,
                    basis=preview.message,
                )
            )

    for item in linked_context:
        if item.package_state != "packaged":
            findings.append(
                HandoffFinding(
                    subject_type="linked_context",
                    subject_id=item.link_id,
                    severity="review",
                    code=f"linked_context_{item.package_state}",
                    basis=item.reason,
                )
            )

    return tuple(findings)


def preview_handoff_manifest(source: dict[str, Any]) -> HandoffManifestPreview:
    """Validate and classify a handoff package manifest without opening files."""

    _validate_manifest(source)
    identity = _identity_from_manifest(source)
    measurements = _measurements_from_manifest(source)
    linked_context = _linked_context_from_manifest(source)
    return HandoffManifestPreview(
        identity=identity,
        classification=_package_classification(
            measurements=measurements,
            linked_context=linked_context,
        ),
        measurements=measurements,
        linked_context=linked_context,
        findings=_findings(
            measurements=measurements,
            linked_context=linked_context,
        ),
    )
