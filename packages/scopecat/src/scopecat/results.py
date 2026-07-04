"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from typing import Any

from scopecat.artifact_reports import (
    ArtifactAvailabilityReport,
    ArtifactChunk,
    ArtifactRequirement,
    ChunkedArtifactManifest,
    PointArtifactStatus,
    assemble_chunked_artifact,
    evaluate_artifact_availability,
)
from scopecat.models.attempt import (
    AttemptValue,
    PointAttemptSummary,
    summarize_point_attempts,
)
from scopecat.models.measurement import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementRecord,
    MeasurementVariable,
    MeasurementVariableRole,
    infer_measurement_dataset_schema,
    validate_measurement_records_against_schema,
)
from scopecat.models.parameter import Quantity


class MeasurementSink:
    """Records typed measurements without exposing the JSONL wire format."""

    def __init__(self, *, run_id: str) -> None:
        self._run_id = run_id
        self._measurements: list[MeasurementRecord] = []

    @property
    def measurements(self) -> tuple[MeasurementRecord, ...]:
        return tuple(self._measurements)

    def record(
        self,
        *,
        point_index: int,
        coordinates: dict[str, Quantity],
        observables: dict[str, Quantity],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._measurements.append(
            MeasurementRecord(
                run_id=self._run_id,
                point_index=point_index,
                coordinates=coordinates,
                observables=observables,
                metadata=metadata or {},
            )
        )


__all__ = [
    "ArtifactAvailabilityReport",
    "ArtifactChunk",
    "ArtifactRequirement",
    "AttemptValue",
    "ChunkedArtifactManifest",
    "MeasurementDType",
    "MeasurementDataset",
    "MeasurementDatasetInputDiagnostics",
    "MeasurementDatasetRole",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementRecord",
    "MeasurementSink",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "PointArtifactStatus",
    "PointAttemptSummary",
    "assemble_chunked_artifact",
    "evaluate_artifact_availability",
    "infer_measurement_dataset_schema",
    "summarize_point_attempts",
    "validate_measurement_records_against_schema",
]
