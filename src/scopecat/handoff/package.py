"""Route-local read-only handoff package projections."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff.tables import HandoffPlotSeries, HandoffTable


@dataclass(frozen=True)
class HandoffFinding:
    """Review finding surfaced by the read-only handoff route."""

    code: str
    severity: str
    subject_type: str
    subject_id: str
    measurement_record_id: str | None = None
    basis: str | None = None
    does_not_claim: str | None = None

    @classmethod
    def from_manifest_finding(cls, finding: dict[str, Any]) -> HandoffFinding:
        return cls(
            code=finding["finding"],
            severity=finding["severity"],
            subject_type=finding["subject_type"],
            subject_id=finding["subject_id"],
            measurement_record_id=finding.get("measurement_record_id"),
            basis=finding.get("basis"),
            does_not_claim=finding.get("does_not_claim"),
        )

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
        if self.does_not_claim is not None:
            result["does_not_claim"] = self.does_not_claim
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

    @classmethod
    def from_manifest_item(cls, item: dict[str, Any]) -> HandoffLinkedContext:
        return cls(
            link_id=item["link_id"],
            kind=item["kind"],
            label=item["label"],
            package_state=item["package_state"],
            materialization=(
                "packaged_payload" if item["package_state"] == "packaged" else "reference_only"
            ),
            linked_measurement_record_ids=tuple(item["linked_measurement_record_ids"]),
            package_path=item.get("package_path"),
            declared_digest=item.get("digest"),
            declared_size_bytes=item.get("size_bytes"),
            context_reference=copy.deepcopy(item.get("context_reference")),
        )

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
class HandoffContextReferenceSummary:
    """Read-only summary of package context references."""

    package_id: str
    measurement_ids: tuple[str, ...]
    context_references: tuple[dict[str, Any], ...]
    untyped_linked_context_ids: tuple[str, ...]

    @property
    def context_reference_count(self) -> int:
        return len(self.context_references)

    @property
    def family_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.context_references:
            family = item["reference_family"]
            counts[family] = counts.get(family, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def prepared_run_context_ids(self) -> tuple[str, ...]:
        return tuple(
            item["reference_id"]
            for item in self.context_references
            if item["reference_family"] == "prepared_run"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_context_reference_summary",
            "summary_policy": {
                "source": "read_only_handoff_package",
                "authority": "operator_review_summary",
                "payload_import": "not_performed",
                "reference_resolution": "not_performed",
                "environment_restoration": "not_performed",
                "code_materialization": "not_performed",
                "storage_mutation": "not_performed",
                "portable_export": "not_produced",
            },
            "package_id": self.package_id,
            "measurement_ids": list(self.measurement_ids),
            "context_reference_count": self.context_reference_count,
            "reference_family_counts": self.family_counts,
            "prepared_run_context_ids": list(self.prepared_run_context_ids),
            "context_references": [copy.deepcopy(item) for item in self.context_references],
            "untyped_linked_context_ids": list(self.untyped_linked_context_ids),
            "does_not_claim": [
                "linked_context_payload_import",
                "reference_resolution",
                "environment_restoration",
                "code_materialization",
                "prepared_run_reconstruction",
                "durable_review_state",
            ],
        }


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
    integrity_check: str
    declared_preview_metadata_authority: str
    declared_preview_columns: tuple[dict[str, str], ...]
    declared_preview_shape: dict[str, Any]
    declared_preview_plot_candidates: tuple[dict[str, Any], ...]
    primary_table: HandoffTable
    preview_table: HandoffTable
    plot_series: tuple[HandoffPlotSeries, ...]
    linked_context: tuple[HandoffLinkedContext, ...]
    findings: tuple[HandoffFinding, ...]
    classification: str = "opened_for_declared_preview"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declared_preview_columns",
            tuple(copy.deepcopy(column) for column in self.declared_preview_columns),
        )
        object.__setattr__(
            self,
            "declared_preview_shape",
            copy.deepcopy(self.declared_preview_shape),
        )
        object.__setattr__(
            self,
            "declared_preview_plot_candidates",
            tuple(copy.deepcopy(candidate) for candidate in self.declared_preview_plot_candidates),
        )

    def plot_series_by_columns(self, *, x: str, y: str) -> HandoffPlotSeries:
        for series in self.plot_series:
            if series.x_name == x and series.y_name == y:
                return series
        raise KeyError(f"{x}:{y}")

    def to_dict(self) -> dict[str, Any]:
        primary_data = {
            "package_path": self.primary_package_path,
            "format": self.primary_format,
            "open_state": "opened",
            "observed_size_bytes": self.observed_size_bytes,
            "integrity_check": self.integrity_check,
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
                "metadata_authority": self.declared_preview_metadata_authority,
                "data_shape": copy.deepcopy(self.declared_preview_shape),
                "declared_columns": tuple(
                    copy.deepcopy(column) for column in self.declared_preview_columns
                ),
                "plot_candidates": tuple(
                    copy.deepcopy(candidate) for candidate in self.declared_preview_plot_candidates
                ),
            },
            "primary_table": {
                "source": self.primary_package_path,
                "columns": self.primary_table.columns,
                "rows": self.primary_table.to_records(),
                "schema_inference": "not_performed",
            },
            "preview_data": {
                "source": self.primary_package_path,
                "row_count": self.preview_table.row_count,
                "preview_rows": self.preview_table.to_records(),
                "plot_series": [
                    {
                        "source": series.source,
                        "x": series.x_name,
                        "y": series.y_name,
                        "points": series.to_records(),
                    }
                    for series in self.plot_series
                ],
                "schema_inference": "not_performed",
            },
            "linked_context": [item.to_dict() for item in self.linked_context],
            "findings": [finding.to_dict() for finding in self.findings],
            "classification": self.classification,
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
    classification: str = "opened_read_only_for_declared_preview"

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
                "classification": self.classification,
                "preview_classification": self.preview_classification,
            },
            "selected_measurements": [measurement.to_dict() for measurement in self.measurements],
            "linked_context": [item.to_dict() for item in self.linked_context],
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def as_open_summary(self) -> dict[str, Any]:
        """Return a copy-safe prototype snapshot.

        This is not the discovery candidate summary shape; policy/non-claim
        details are owned by route docs, tests, and concise runtime fields.
        """

        return copy.deepcopy(self.to_dict())


def summarize_package_context_references(
    package: HandoffPackage,
) -> HandoffContextReferenceSummary:
    """Summarize reference-only context visible in an opened handoff package."""

    context_references = []
    untyped_context_ids = []
    for item in package.linked_context:
        if item.context_reference is None:
            untyped_context_ids.append(item.link_id)
            continue
        reference = item.context_reference
        context_references.append(
            {
                "link_id": item.link_id,
                "kind": item.kind,
                "label": item.label,
                "package_state": item.package_state,
                "materialization": item.materialization,
                "package_path": item.package_path,
                "linked_measurement_record_ids": list(item.linked_measurement_record_ids),
                "reference_id": reference["reference_id"],
                "reference_kind": reference["reference_kind"],
                "reference_family": reference["reference_family"],
                "reference_materialization": reference["materialization"],
                "payload_import": reference["payload_import"],
            }
        )
    return HandoffContextReferenceSummary(
        package_id=package.package_id,
        measurement_ids=package.measurement_ids,
        context_references=tuple(context_references),
        untyped_linked_context_ids=tuple(untyped_context_ids),
    )
