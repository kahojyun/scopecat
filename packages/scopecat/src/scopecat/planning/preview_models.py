"""Stable user-facing facts available before an experiment runs."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.measurements.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int
    coordinates: dict[str, object]


@dataclass(frozen=True)
class ExperimentPreviewRecord:
    id: str
    kind: str
    unit: str | None
    dtype: str
    dims: tuple[str, ...]
    shape: tuple[int, ...]


@dataclass(frozen=True)
class ExperimentPreview:
    """Stable experiment shape that a user can review before execution."""

    experiment_id: str
    experiment_kind: str
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    points: tuple[ExperimentPreviewPoint, ...]
    records: tuple[ExperimentPreviewRecord, ...]

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def primary_observables(self) -> tuple[str, ...]:
        if self.schema is not None:
            return tuple(self.schema.primary_observables)
        return tuple(
            record.id for record in self.records if record.kind == "observable"
        )


__all__ = [
    "ExperimentPreview",
    "ExperimentPreviewPoint",
    "ExperimentPreviewRecord",
]
