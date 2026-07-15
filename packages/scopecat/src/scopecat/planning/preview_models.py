"""Notebook-facing experiment preview summaries."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.state import StateLiteral
from scopecat.measurements.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int
    point_uid: str
    coordinates: dict[str, object]


@dataclass(frozen=True)
class ExperimentPreviewRecord:
    id: str
    kind: str
    resource_port_id: str | None
    physical_resource_id: str | None
    capability: str | None
    unit: str | None
    dtype: str
    dims: tuple[str, ...]
    shape: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.resource_port_id is not None and self.physical_resource_id is not None:
            msg = "preview record cannot target both logical and physical resources"
            raise ValueError(msg)


@dataclass(frozen=True)
class ExperimentPreviewChannelBinding:
    entity_id: str
    channel_id: str
    line_id: str | None
    capability: str | None
    group_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExperimentPreviewStateChange:
    point_index: int
    resource_id: str
    resource_port_id: str | None
    capability_id: str
    field_path: str
    before: object | None
    after: object
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[ExperimentPreviewChannelBinding, ...] = ()

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


@dataclass(frozen=True)
class ExperimentPreviewResolvedRoute:
    point_index: int
    port_id: str
    resource_id: str
    resource_kind: str
    entity_ids: tuple[str, ...]
    served_entity_ids: tuple[str, ...]
    product_axis_order: tuple[str, ...]
    channel_bindings: tuple[ExperimentPreviewChannelBinding, ...]


@dataclass(frozen=True)
class ExperimentPreviewRoute:
    port_id: str
    capabilities: tuple[str, ...]
    entity_expr_count: int
    fixed_resource_id: str | None
    resolved: tuple[ExperimentPreviewResolvedRoute, ...] = ()


@dataclass(frozen=True)
class ExperimentPreviewStateField:
    point_index: int
    resource_id: str
    resource_port_id: str | None
    capability_id: str
    field_path: str
    value: StateLiteral
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[ExperimentPreviewChannelBinding, ...] = ()


@dataclass(frozen=True)
class ExperimentPreviewPayload:
    semantic_operation_id: str
    schema_id: str
    state_fields: tuple[ExperimentPreviewStateTarget, ...]
    dependencies: dict[str, tuple[str, ...]]


@dataclass(frozen=True, order=True)
class ExperimentPreviewStateTarget:
    resource_id: str
    capability_id: str
    field_path: str
    entity_ids: tuple[str, ...] = ()
    resource_port_id: str | None = None

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


@dataclass(frozen=True)
class ExperimentPreviewComputeStep:
    point_index: int
    semantic_operation_id: str
    payload_id: str | None
    schema_id: str | None
    dependencies: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ExperimentPreviewRuntimeSummary:
    route_count: int
    state_field_count: int
    compute_operation_count: int
    compute_step_count: int
    payload_count: int


@dataclass(frozen=True)
class ExperimentPreview:
    experiment_id: str
    experiment_kind: str
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    points: tuple[ExperimentPreviewPoint, ...]
    records: tuple[ExperimentPreviewRecord, ...]
    state_changes: tuple[ExperimentPreviewStateChange, ...]
    routes: tuple[ExperimentPreviewRoute, ...]
    state_fields: tuple[ExperimentPreviewStateField, ...]
    payloads: tuple[ExperimentPreviewPayload, ...]
    compute_steps: tuple[ExperimentPreviewComputeStep, ...]

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def runtime(self) -> ExperimentPreviewRuntimeSummary:
        return ExperimentPreviewRuntimeSummary(
            route_count=len(self.routes),
            state_field_count=len(self.state_fields),
            compute_operation_count=len(
                {step.semantic_operation_id for step in self.compute_steps}
            ),
            compute_step_count=len(self.compute_steps),
            payload_count=len(self.payloads),
        )

    @property
    def dataset_dimensions(self) -> dict[str, int]:
        dimensions = (
            {
                dimension.id: dimension.size
                for dimension in self.schema.dimensions
                if dimension.size is not None
            }
            if self.schema is not None
            else {}
        )
        if (
            self.schema is not None
            and any(dimension.id == "point" for dimension in self.schema.dimensions)
        ) or any("point" in record.dims for record in self.records):
            dimensions["point"] = self.point_count
        return dimensions

    @property
    def primary_observables(self) -> tuple[str, ...]:
        if self.schema is not None:
            return tuple(self.schema.primary_observables)
        return tuple(
            record.id for record in self.records if record.kind == "observable"
        )


__all__ = [
    "ExperimentPreview",
    "ExperimentPreviewChannelBinding",
    "ExperimentPreviewComputeStep",
    "ExperimentPreviewPayload",
    "ExperimentPreviewPoint",
    "ExperimentPreviewRecord",
    "ExperimentPreviewResolvedRoute",
    "ExperimentPreviewRoute",
    "ExperimentPreviewRuntimeSummary",
    "ExperimentPreviewStateChange",
    "ExperimentPreviewStateField",
    "ExperimentPreviewStateTarget",
]
