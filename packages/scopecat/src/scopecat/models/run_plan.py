"""Durable user-visible execution plan records."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.models._run_request_values import normalize_json_value
from scopecat.models.entity import EntityRef
from scopecat.models.measurement import CoordinateValue, MeasurementDatasetSchema
from scopecat.models.parameter import Quantity

RUN_PLAN_RECORD_SCHEMA_VERSION = "scopecat.run_plan_record.v2"


class _RunPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunPlanDeferredValue(_RunPlanModel):
    """Durable marker for a value produced only while the run executes.

    The transient producer identity deliberately is not persisted.  That keeps
    compiler node names and graph topology out of the accepted-plan contract.
    """

    kind: Literal["deferred"] = "deferred"


class RunPlanPayloadValue(_RunPlanModel):
    """Durable payload schema descriptor; the opaque Python payload is omitted."""

    kind: Literal["payload"] = "payload"
    schema_id: str


type RunPlanValue = Annotated[
    Quantity
    | EntityRef
    | RunPlanDeferredValue
    | RunPlanPayloadValue
    | str
    | bool
    | int
    | float
    | None,
    Field(union_mode="left_to_right"),
]


def _validate_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = f"{path} must contain only finite numbers"
            raise ValueError(msg)
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(cast("list[object] | tuple[object, ...]", value)):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = f"{path} must contain only string mapping keys"
                raise ValueError(msg)
            _validate_json_value(item, path=f"{path}.{key}")
        return
    msg = f"{path} must contain only durable JSON values"
    raise ValueError(msg)


def _validate_run_plan_value(value: object, *, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        msg = f"{path} must be finite"
        raise ValueError(msg)
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            msg = f"{path} quantity value must be finite"
            raise ValueError(msg)
        return
    if isinstance(value, EntityRef):
        _validate_json_value(value.metadata, path=f"{path}.metadata")


def _normalize_entity_ref(value: object) -> object:
    if not isinstance(value, EntityRef):
        return value
    return EntityRef.model_validate(value.model_dump(mode="python"))


def _normalized_json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    normalized = normalize_json_value(value)
    if not isinstance(normalized, dict):
        raise AssertionError("JSON mapping normalization must produce an object")
    return cast("dict[str, object]", normalized)


class RunPlanPoint(_RunPlanModel):
    point_index: int = Field(ge=0)
    point_uid: str
    coordinates: dict[str, CoordinateValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_coordinate_values(self) -> RunPlanPoint:
        normalized: dict[str, CoordinateValue] = {}
        for coordinate_id, value in self.coordinates.items():
            _validate_run_plan_value(
                value,
                path=f"run plan coordinate {coordinate_id!r}",
            )
            normalized[coordinate_id] = cast(
                "CoordinateValue",
                _normalize_entity_ref(value),
            )
        self.coordinates = normalized
        return self


class RunPlanOutput(_RunPlanModel):
    id: str
    kind: str
    source: str
    resource: str | None = None
    capability: str | None = None
    unit: str | None = None
    dtype: str
    dims: list[str] = Field(default_factory=list)
    shape: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dimension_shape(self) -> RunPlanOutput:
        if len(self.dims) != len(self.shape):
            msg = f"run plan output {self.id!r} dims and shape must have equal length"
            raise ValueError(msg)
        return self


class RunPlanStateChange(_RunPlanModel):
    point_index: int = Field(ge=0)
    resource: str
    field: str
    before: RunPlanValue = None
    after: RunPlanValue

    @model_validator(mode="after")
    def validate_values(self) -> RunPlanStateChange:
        _validate_run_plan_value(self.before, path="run plan state change before")
        _validate_run_plan_value(self.after, path="run plan state change after")
        self.before = cast("RunPlanValue", _normalize_entity_ref(self.before))
        self.after = cast("RunPlanValue", _normalize_entity_ref(self.after))
        return self


class RunPlanChannelBinding(_RunPlanModel):
    entity_id: str
    channel_id: str
    line_id: str | None = None
    capability: str | None = None
    group_ids: list[str] = Field(default_factory=list)


class RunPlanResolvedRoute(_RunPlanModel):
    point_index: int = Field(ge=0)
    port_id: str
    resource_id: str
    entity_ids: list[str] = Field(default_factory=list)
    product_axis_order: list[str] = Field(default_factory=list)
    channel_bindings: list[RunPlanChannelBinding] = Field(default_factory=list)


class RunPlanRoute(_RunPlanModel):
    port_id: str
    capabilities: list[str] = Field(default_factory=list)
    entity_expr_count: int = Field(ge=0)
    fixed_resource: str | None = None
    resolved: list[RunPlanResolvedRoute] = Field(default_factory=list)


class RunPlanRecord(_RunPlanModel):
    """Stable projection of the plan accepted for one execution."""

    schema_version: Literal["scopecat.run_plan_record.v2"] = (
        RUN_PLAN_RECORD_SCHEMA_VERSION
    )
    experiment_id: str
    experiment_kind: str
    point_count: int = Field(ge=0)
    expected_dataset_schema: MeasurementDatasetSchema | None = None
    coordinate_ids: list[str] = Field(default_factory=list)
    points: list[RunPlanPoint] = Field(default_factory=list)
    records: list[RunPlanOutput] = Field(default_factory=list)
    state_changes: list[RunPlanStateChange] = Field(default_factory=list)
    routes: list[RunPlanRoute] = Field(default_factory=list)
    dataset_dimensions: dict[str, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    primary_observables: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> RunPlanRecord:
        self._validate_points()
        self._validate_point_references()
        self._validate_primary_observables()
        self._validate_expected_dataset_schema()
        self._validate_dataset_dimensions()
        return self

    def _validate_points(self) -> None:
        if len(self.points) != self.point_count:
            msg = "run plan point_count must equal the number of points"
            raise ValueError(msg)
        point_indices = [point.point_index for point in self.points]
        if point_indices != list(range(self.point_count)):
            msg = (
                "run plan point indices must be unique, contiguous, "
                "and ordered from zero"
            )
            raise ValueError(msg)
        point_uids = [point.point_uid for point in self.points]
        if len(point_uids) != len(set(point_uids)):
            msg = "run plan point UIDs must be unique"
            raise ValueError(msg)
        if len(self.coordinate_ids) != len(set(self.coordinate_ids)):
            msg = "run plan coordinate_ids must be unique"
            raise ValueError(msg)
        coordinate_ids = set(self.coordinate_ids)
        for point in self.points:
            if set(point.coordinates) != coordinate_ids:
                msg = (
                    f"run plan point {point.point_index} coordinate keys must equal "
                    "coordinate_ids"
                )
                raise ValueError(msg)

    def _validate_point_references(self) -> None:
        for change in self.state_changes:
            if change.point_index >= self.point_count:
                msg = "run plan state change point_index is outside the point range"
                raise ValueError(msg)
        for route in self.routes:
            for resolved in route.resolved:
                if resolved.point_index >= self.point_count:
                    msg = (
                        "run plan resolved route point_index is outside the point range"
                    )
                    raise ValueError(msg)

    def _validate_primary_observables(self) -> None:
        record_ids = {record.id for record in self.records}
        missing = sorted(set(self.primary_observables) - record_ids)
        if missing:
            msg = "run plan primary observables must reference records: " + ", ".join(
                missing
            )
            raise ValueError(msg)

    def _validate_expected_dataset_schema(self) -> None:
        schema = self.expected_dataset_schema
        if schema is None:
            return
        _validate_json_value(
            schema.metadata,
            path="run plan expected dataset schema metadata",
        )
        schema.metadata = _normalized_json_mapping(schema.metadata)
        for dimension in schema.dimensions:
            _validate_json_value(
                dimension.metadata,
                path=f"run plan dataset dimension {dimension.id!r} metadata",
            )
            dimension.metadata = _normalized_json_mapping(dimension.metadata)
        for variable in schema.variables:
            _validate_json_value(
                variable.metadata,
                path=f"run plan dataset variable {variable.id!r} metadata",
            )
            variable.metadata = _normalized_json_mapping(variable.metadata)
        if schema.primary_coordinates != self.coordinate_ids:
            msg = (
                "run plan expected dataset schema primary_coordinates must equal "
                "coordinate_ids"
            )
            raise ValueError(msg)
        if schema.primary_observables != self.primary_observables:
            msg = (
                "run plan expected dataset schema primary_observables must equal "
                "primary_observables"
            )
            raise ValueError(msg)

        record_by_id = {record.id: record for record in self.records}
        if len(record_by_id) != len(self.records):
            msg = "run plan record IDs must be unique"
            raise ValueError(msg)
        observable_by_id = {
            variable.id: variable
            for variable in schema.variables
            if variable.role == "observable"
        }
        if set(observable_by_id) != set(record_by_id):
            msg = (
                "run plan expected dataset schema observable variable IDs must equal "
                "record IDs"
            )
            raise ValueError(msg)

        for record_id, record in record_by_id.items():
            variable = observable_by_id[record_id]
            if record.kind != "observable":
                msg = f"run plan record {record_id!r} kind must be 'observable'"
                raise ValueError(msg)
            if variable.dtype != record.dtype:
                msg = (
                    f"run plan record {record_id!r} dtype must equal its expected "
                    "dataset variable dtype"
                )
                raise ValueError(msg)
            if variable.unit != record.unit:
                msg = (
                    f"run plan record {record_id!r} unit must equal its expected "
                    "dataset variable unit"
                )
                raise ValueError(msg)
            if variable.dims != record.dims or variable.shape != record.shape:
                msg = (
                    f"run plan record {record_id!r} dims and shape must equal its "
                    "expected dataset variable dims and shape"
                )
                raise ValueError(msg)

    def _validate_dataset_dimensions(self) -> None:
        known_ids: set[str] = set()
        known_sizes: dict[str, int] = {}

        def record_size(dimension_id: str, size: int, source: str) -> None:
            known_ids.add(dimension_id)
            existing = known_sizes.get(dimension_id)
            if existing is not None and existing != size:
                msg = (
                    f"run plan dimension {dimension_id!r} has conflicting sizes "
                    f"{existing} and {size} ({source})"
                )
                raise ValueError(msg)
            known_sizes[dimension_id] = size

        schema = self.expected_dataset_schema
        if schema is not None:
            for dimension in schema.dimensions:
                known_ids.add(dimension.id)
                if dimension.size is not None:
                    record_size(
                        dimension.id,
                        dimension.size,
                        "expected dataset schema",
                    )
            for variable in schema.variables:
                for dimension_id, size in zip(
                    variable.dims,
                    variable.shape,
                    strict=True,
                ):
                    record_size(
                        dimension_id,
                        size,
                        f"dataset variable {variable.id!r}",
                    )
        for record in self.records:
            for dimension_id, size in zip(record.dims, record.shape, strict=True):
                record_size(
                    dimension_id,
                    size,
                    f"output {record.id!r}",
                )
        if "point" in known_ids:
            record_size("point", self.point_count, "point_count")

        unknown = sorted(set(self.dataset_dimensions) - known_ids)
        if unknown:
            msg = (
                "run plan dataset_dimensions contains unknown dimensions: "
                + ", ".join(unknown)
            )
            raise ValueError(msg)
        missing = sorted(set(known_sizes) - set(self.dataset_dimensions))
        if missing:
            msg = (
                "run plan dataset_dimensions is missing known dimensions: "
                + ", ".join(missing)
            )
            raise ValueError(msg)
        for dimension_id, size in known_sizes.items():
            if self.dataset_dimensions[dimension_id] != size:
                msg = (
                    f"run plan dataset dimension {dimension_id!r} must have size {size}"
                )
                raise ValueError(msg)


__all__ = [
    "RUN_PLAN_RECORD_SCHEMA_VERSION",
    "RunPlanChannelBinding",
    "RunPlanDeferredValue",
    "RunPlanOutput",
    "RunPlanPayloadValue",
    "RunPlanPoint",
    "RunPlanRecord",
    "RunPlanResolvedRoute",
    "RunPlanRoute",
    "RunPlanStateChange",
]
