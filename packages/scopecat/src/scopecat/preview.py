"""Notebook-facing experiment preview summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from scopecat.models.run import RunConfigSource
from scopecat.models.state import StateLiteral
from scopecat.problems import Problem, has_blocking_problems
from scopecat.results import MeasurementDatasetSchema


def _empty_inputs() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class ExperimentPreviewPoint:
    point_index: int
    point_uid: str
    coordinates: dict[str, object]


@dataclass(frozen=True)
class ExperimentPreviewRecord:
    id: str
    kind: str
    producer_kind: Literal["instrument"]
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
    problems: tuple[Problem, ...]
    summary: ExperimentPreview | None = None
    template_id: str | None = None
    inputs: Mapping[str, object] = field(default_factory=_empty_inputs)
    config_source: RunConfigSource | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "problems", tuple(self.problems))
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )

    @property
    def ok(self) -> bool:
        return not has_blocking_problems(self.problems)


@dataclass(frozen=True)
class PreviewExperimentResult:
    summary: ExperimentPreview
    problems: tuple[Problem, ...]
    template_id: str | None = None
    inputs: Mapping[str, object] = field(default_factory=_empty_inputs)
    config_source: RunConfigSource | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "problems", tuple(self.problems))
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )

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
    "ExperimentPreviewStateTarget",
    "PreviewExperimentResult",
    "ValidateExperimentResult",
]
