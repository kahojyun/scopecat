"""Notebook-facing experiment preview summaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.diagnostics import Diagnostic
from scopecat.models.run import RunConfigSource
from scopecat.models.state import StateLiteral
from scopecat.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int
    point_uid: str
    coordinates: dict[str, object]


@dataclass(frozen=True)
class ExperimentPreviewRecord:
    id: str
    kind: str
    source: str
    resource: str | None
    capability: str | None
    unit: str | None
    dtype: str
    dims: tuple[str, ...]
    shape: tuple[int, ...]


@dataclass(frozen=True)
class ExperimentPreviewStateChange:
    point_index: int
    resource: str
    field: str
    before: object | None
    after: object


@dataclass(frozen=True)
class ExperimentPreviewChannelBinding:
    entity_id: str
    channel_id: str
    line_id: str | None
    capability: str | None
    group_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExperimentPreviewResolvedRoute:
    point_index: int
    port_id: str
    resource_id: str
    entity_ids: tuple[str, ...]
    product_axis_order: tuple[str, ...]
    channel_bindings: tuple[ExperimentPreviewChannelBinding, ...]


@dataclass(frozen=True)
class ExperimentPreviewRoute:
    port_id: str
    capabilities: tuple[str, ...]
    entity_expr_count: int
    fixed_resource: str | None
    resolved: tuple[ExperimentPreviewResolvedRoute, ...] = ()


@dataclass(frozen=True)
class ExperimentPreviewStateField:
    point_index: int
    resource_id: str
    capability_id: str
    field_path: str
    value: StateLiteral
    channel_bindings: tuple[ExperimentPreviewChannelBinding, ...] = ()


@dataclass(frozen=True)
class ExperimentPreviewPayload:
    node_id: str
    schema_id: str
    state_fields: tuple[str, ...]
    dependencies: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ExperimentPreviewComputeStep:
    point_index: int
    node_id: str
    payload_id: str | None
    schema_id: str | None
    dependencies: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ExperimentPreviewRuntimeSummary:
    route_count: int
    state_field_count: int
    compute_node_count: int
    compute_step_count: int
    payload_count: int


@dataclass(frozen=True)
class ExperimentPreview:
    experiment_id: str
    experiment_kind: str
    point_count: int
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    points: tuple[ExperimentPreviewPoint, ...]
    records: tuple[ExperimentPreviewRecord, ...]
    state_changes: tuple[ExperimentPreviewStateChange, ...]
    routes: tuple[ExperimentPreviewRoute, ...]
    state_fields: tuple[ExperimentPreviewStateField, ...]
    payloads: tuple[ExperimentPreviewPayload, ...]
    compute_steps: tuple[ExperimentPreviewComputeStep, ...]
    runtime: ExperimentPreviewRuntimeSummary
    dataset_dimensions: dict[str, int]
    primary_observables: tuple[str, ...]


@dataclass(frozen=True)
class ValidateExperimentResult:
    diagnostics: tuple[Diagnostic, ...]
    summary: ExperimentPreview | None = None
    template_id: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    config_source: RunConfigSource | None = None

    @property
    def ok(self) -> bool:
        return not any(
            diagnostic.severity in {"error", "blocker"}
            for diagnostic in self.diagnostics
        )


@dataclass(frozen=True)
class PreviewExperimentResult:
    summary: ExperimentPreview
    diagnostics: tuple[Diagnostic, ...]
    template_id: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    config_source: RunConfigSource | None = None

    @property
    def experiment_id(self) -> str:
        return self.summary.experiment_id

    @property
    def experiment_kind(self) -> str:
        return self.summary.experiment_kind

    @property
    def point_count(self) -> int:
        return self.summary.point_count

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self.summary.coordinate_ids

    @property
    def schema(self) -> MeasurementDatasetSchema | None:
        return self.summary.schema

    @property
    def points(self) -> tuple[ExperimentPreviewPoint, ...]:
        return self.summary.points

    @property
    def records(self) -> tuple[ExperimentPreviewRecord, ...]:
        return self.summary.records

    @property
    def state_changes(self) -> tuple[ExperimentPreviewStateChange, ...]:
        return self.summary.state_changes

    @property
    def routes(self) -> tuple[ExperimentPreviewRoute, ...]:
        return self.summary.routes

    @property
    def state_fields(self) -> tuple[ExperimentPreviewStateField, ...]:
        return self.summary.state_fields

    @property
    def payloads(self) -> tuple[ExperimentPreviewPayload, ...]:
        return self.summary.payloads

    @property
    def compute_steps(self) -> tuple[ExperimentPreviewComputeStep, ...]:
        return self.summary.compute_steps

    @property
    def runtime(self) -> ExperimentPreviewRuntimeSummary:
        return self.summary.runtime

    @property
    def dataset_dimensions(self) -> dict[str, int]:
        return self.summary.dataset_dimensions

    @property
    def primary_observables(self) -> tuple[str, ...]:
        return self.summary.primary_observables


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
    "PreviewExperimentResult",
    "ValidateExperimentResult",
]
