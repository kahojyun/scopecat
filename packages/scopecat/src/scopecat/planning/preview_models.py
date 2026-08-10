"""Stable user-facing facts available before an experiment runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.measurements.results import MeasurementDatasetSchema
from scopecat.program.measurement_types import MeasurementVariableRole


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int
    coordinates: dict[str, object]


@dataclass(frozen=True)
class ExperimentPreviewRecord:
    id: str
    role: MeasurementVariableRole
    recording_group_id: str | None
    unit: str | None
    dtype: str
    dims: tuple[str, ...]
    shape: tuple[int | None, ...]


@dataclass(frozen=True)
class ExperimentPreviewCompute:
    """Why one live compute runs at its compiler-selected placement."""

    id: str
    placement: Literal["host", "observation"]
    input_names: tuple[str, ...]
    outputs: tuple[str, ...]
    demanded_by: tuple[str, ...]
    implementation_id: str | None = None


@dataclass(frozen=True)
class ExperimentPreview:
    """Stable experiment shape that a user can review before execution."""

    experiment_id: str
    experiment_kind: str
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    points: tuple[ExperimentPreviewPoint, ...]
    records: tuple[ExperimentPreviewRecord, ...]
    computes: tuple[ExperimentPreviewCompute, ...] = ()

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def primary_observables(self) -> tuple[str, ...]:
        if self.schema is not None:
            return tuple(self.schema.primary_observables)
        return tuple(
            record.id for record in self.records if record.role == "observable"
        )

    @property
    def host_compute_ids(self) -> tuple[str, ...]:
        return tuple(
            compute.id for compute in self.computes if compute.placement == "host"
        )

    @property
    def observation_compute_ids(self) -> tuple[str, ...]:
        return tuple(
            compute.id
            for compute in self.computes
            if compute.placement == "observation"
        )
