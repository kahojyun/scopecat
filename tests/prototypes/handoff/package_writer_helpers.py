from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from scopecat.handoff.writer import (
    HandoffPackageBundleItem,
    HandoffPackageIdentity,
    HandoffPackageLinkedContext,
    HandoffPackagePreviewColumn,
    HandoffPackagePreviewMetadata,
    HandoffPackagePrimaryData,
    HandoffPackageSelectedMeasurement,
    HandoffPackageWriteReceipt,
    HandoffPackageWriteRequest,
    HandoffPackageWriteSource,
    write_package_from_source,
)


def write_package_from_fixture_source(
    source: dict[str, Any],
    *,
    source_root: Path,
    package_root: Path,
) -> HandoffPackageWriteReceipt:
    return write_package_from_source(
        writer_source_from_fixture(source),
        source_root=source_root,
        package_root=package_root,
    )


def writer_source_from_fixture(source: dict[str, Any]) -> HandoffPackageWriteSource:
    request = source["package_write_request"]
    identity = source["package_identity"]
    return HandoffPackageWriteSource(
        request=HandoffPackageWriteRequest(
            request_id=request["request_id"],
            package_dir=request["package_dir"],
            manifest_path=request["manifest_path"],
        ),
        identity=HandoffPackageIdentity(
            package_id=identity["package_id"],
            display_name=identity["display_name"],
            created_by=identity["created_by"],
            source_export_summary_id=identity["source_export_summary_id"],
            display_path=identity["display_path"],
            local_path_redacted=identity["local_path_redacted"],
        ),
        selected_measurements=tuple(
            _selected_measurement(record) for record in source["selected_measurements"]
        ),
        linked_context=tuple(_linked_context(item) for item in source["linked_context"]),
    )


def _selected_measurement(source: dict[str, Any]) -> HandoffPackageSelectedMeasurement:
    primary = source["primary_data"]
    return HandoffPackageSelectedMeasurement(
        measurement_record_id=source["measurement_record_id"],
        legacy_data_id=source["legacy_data_id"],
        label=source["label"],
        experiment_type=source["experiment_type"],
        target=source["target"],
        primary_data=HandoffPackagePrimaryData(
            kind=primary["kind"],
            label=primary["label"],
            source_path=primary["source_path"],
            expected_digest=primary["expected_digest"],
            expected_size_bytes=primary["expected_size_bytes"],
            package_path=primary["package_path"],
            include_status=primary["include_status"],
            relation=primary["relation"],
            authority=primary["authority"],
            format=primary["format"],
            package_state=primary["package_state"],
            reason=primary["reason"],
        ),
        declared_preview_metadata=_preview_metadata(source["declared_preview_metadata"]),
        default_bundle=tuple(_bundle_item(item) for item in source["default_bundle"]),
    )


def _preview_metadata(source: dict[str, Any]) -> HandoffPackagePreviewMetadata:
    return HandoffPackagePreviewMetadata(
        status=source["status"],
        metadata_authority=source["metadata_authority"],
        declared_columns=tuple(
            HandoffPackagePreviewColumn(
                name=column["name"],
                role=column["role"],
                label=column["label"],
                unit=column["unit"],
            )
            for column in source["declared_columns"]
        ),
    )


def _bundle_item(source: dict[str, Any]) -> HandoffPackageBundleItem:
    return HandoffPackageBundleItem(
        item_id=source["item_id"],
        kind=source["kind"],
        label=source["label"],
        package_path=source["package_path"],
        include_status=source["include_status"],
        relation=source["relation"],
        authority=source["authority"],
        package_state=source["package_state"],
        reason=source["reason"],
    )


def _linked_context(source: dict[str, Any]) -> HandoffPackageLinkedContext:
    return HandoffPackageLinkedContext(
        link_id=source["link_id"],
        kind=source["kind"],
        label=source["label"],
        package_path=source["package_path"],
        include_status=source["include_status"],
        relation=source["relation"],
        authority=source["authority"],
        package_state=source["package_state"],
        reason=source["reason"],
        linked_measurement_record_ids=tuple(source["linked_measurement_record_ids"]),
        source_path=source.get("source_path"),
        expected_digest=source.get("expected_digest"),
        expected_size_bytes=source.get("expected_size_bytes"),
        context_reference=(
            None
            if source.get("context_reference") is None
            else copy.deepcopy(source["context_reference"])
        ),
    )
