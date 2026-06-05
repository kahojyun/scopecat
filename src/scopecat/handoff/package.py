"""Route-local read-only handoff package projections."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff._declared_preview import HandoffPackagePreviewMetadata
from scopecat.handoff.tables import HandoffTable


@dataclass(frozen=True)
class HandoffFinding:
    """Review finding surfaced by the read-only handoff route."""

    code: str
    severity: str
    subject_type: str
    subject_id: str
    measurement_record_id: str | None = None
    basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "finding": self.code,
            "severity": self.severity,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
        }
        if self.measurement_record_id is not None:
            result["measurement_record_id"] = self.measurement_record_id
        if self.basis is not None:
            result["basis"] = self.basis
        return result


@dataclass(frozen=True)
class HandoffLinkedContext:
    """Reference-only linked context visible during package inspection."""

    link_id: str
    kind: str
    label: str
    package_state: str
    materialization: str
    linked_measurement_record_ids: tuple[str, ...]
    package_path: str | None = None
    declared_digest: str | None = None
    declared_size_bytes: int | None = None
    context_reference: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "package_state": self.package_state,
            "materialization": self.materialization,
            "linked_measurement_record_ids": list(self.linked_measurement_record_ids),
        }
        if self.package_path is not None:
            result["package_path"] = self.package_path
        if self.declared_digest is not None:
            result["declared_digest"] = self.declared_digest
        if self.declared_size_bytes is not None:
            result["declared_size_bytes"] = self.declared_size_bytes
        if self.context_reference is not None:
            result["context_reference"] = copy.deepcopy(self.context_reference)
        return result


@dataclass(frozen=True)
class HandoffMeasurement:
    """Route-local projection of one opened handoff package measurement."""

    measurement_record_id: str
    legacy_data_id: int
    label: str
    experiment_type: str
    target: str
    primary_package_path: str
    primary_format: str
    declared_digest: str | None
    declared_size_bytes: int | None
    observed_size_bytes: int
    declared_preview_metadata: HandoffPackagePreviewMetadata
    primary_table: HandoffTable
    preview_table: HandoffTable
    linked_context: tuple[HandoffLinkedContext, ...]
    findings: tuple[HandoffFinding, ...]

    @property
    def declared_preview_metadata_authority(self) -> str:
        return self.declared_preview_metadata.metadata_authority

    @property
    def declared_preview_columns(self) -> tuple[dict[str, str], ...]:
        return tuple(
            column.to_manifest() for column in self.declared_preview_metadata.declared_columns
        )

    def to_dict(self) -> dict[str, Any]:
        primary_data = {
            "package_path": self.primary_package_path,
            "format": self.primary_format,
            "observed_size_bytes": self.observed_size_bytes,
        }
        if self.declared_digest is not None:
            primary_data["declared_digest"] = self.declared_digest
        if self.declared_size_bytes is not None:
            primary_data["declared_size_bytes"] = self.declared_size_bytes

        return {
            "measurement_record_id": self.measurement_record_id,
            "legacy_data_id": self.legacy_data_id,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "target": self.target,
            "primary_data": primary_data,
            "declared_preview": {
                "status": "preview_ready",
                "metadata_authority": self.declared_preview_metadata.metadata_authority,
                "declared_columns": self.declared_preview_columns,
            },
            "primary_table": {
                "source": self.primary_package_path,
                "columns": self.primary_table.columns,
                "rows": self.primary_table.to_records(),
            },
            "preview_data": {
                "source": self.primary_package_path,
                "row_count": self.preview_table.row_count,
                "preview_rows": self.preview_table.to_records(),
            },
            "linked_context": [item.to_dict() for item in self.linked_context],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class HandoffPackage:
    """Read-only route projection for a Scopecat-authored handoff package."""

    package_id: str
    display_name: str
    created_by: str
    source_export_summary_id: str
    preview_classification: str
    measurements: tuple[HandoffMeasurement, ...]
    linked_context: tuple[HandoffLinkedContext, ...]
    findings: tuple[HandoffFinding, ...]
    manifest_path: str = "package-manifest.json"

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return tuple(measurement.measurement_record_id for measurement in self.measurements)

    def measurement(self, measurement_record_id: str) -> HandoffMeasurement:
        for measurement in self.measurements:
            if measurement.measurement_record_id == measurement_record_id:
                return measurement
        raise KeyError(measurement_record_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": {
                "package_id": self.package_id,
                "display_name": self.display_name,
                "created_by": self.created_by,
                "source_export_summary_id": self.source_export_summary_id,
                "manifest_path": self.manifest_path,
                "preview_classification": self.preview_classification,
            },
            "selected_measurements": [measurement.to_dict() for measurement in self.measurements],
            "linked_context": [item.to_dict() for item in self.linked_context],
            "findings": [finding.to_dict() for finding in self.findings],
        }
