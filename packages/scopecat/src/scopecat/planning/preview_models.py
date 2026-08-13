"""Stable user-facing facts available before an experiment runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.inspection import CompiledArtifactInspection
from scopecat.program.measurement_types import MeasurementVariableRole
from scopecat.records.measurement import MeasurementDatasetSchema


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int | None
    coordinates: dict[str, object]
    proposal_fingerprint: str | None = None
    source: Literal["author", "optimizer", "operator"] = "author"

    @property
    def is_planned(self) -> bool:
        return self.point_index is not None


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
    implementation: str
    deterministic: bool
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    demanded_by: tuple[str, ...]
    captures: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentPreviewBinding:
    """One user value classified by ownership rather than authoring syntax."""

    id: str
    kind: Literal["input", "coordinate", "parameter"]
    owner: Literal["invocation", "point-plan", "configuration"]
    origin: Literal["default", "override", "values", "range", "around"] | None


@dataclass(frozen=True)
class ExperimentPreviewBindingRef:
    """Typed identity of one value in the preview binding graph."""

    id: str
    kind: Literal["input", "coordinate", "parameter"]


@dataclass(frozen=True)
class ExperimentPreviewBindingEdge:
    """One parameter relationship without delimiter-encoded provenance."""

    source: ExperimentPreviewBindingRef
    target: ExperimentPreviewBindingRef
    relation: Literal["centers", "overlays"]


@dataclass(frozen=True)
class ExperimentPreviewDomainInspection:
    """One target-owned, non-durable inspection for the selected point."""

    operation_id: str
    point_index: int | None
    target_id: str
    artifact_id: str
    artifact_fingerprint: str
    content: CompiledArtifactInspection


@dataclass(frozen=True)
class ExperimentPreview:
    """Stable experiment shape that a user can review before execution."""

    experiment_id: str
    experiment_kind: str
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    total_point_count: int
    points: tuple[ExperimentPreviewPoint, ...]
    points_truncated: bool
    records: tuple[ExperimentPreviewRecord, ...]
    selected_point: ExperimentPreviewPoint | None = None
    domain_inspections: tuple[ExperimentPreviewDomainInspection, ...] = ()
    computes: tuple[ExperimentPreviewCompute, ...] = ()
    bindings: tuple[ExperimentPreviewBinding, ...] = ()
    binding_edges: tuple[ExperimentPreviewBindingEdge, ...] = ()

    @property
    def point_count(self) -> int:
        return self.total_point_count

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
