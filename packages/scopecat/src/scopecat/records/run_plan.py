"""Durable user-visible execution plan records."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.entity import EntityRef
from scopecat.records.measurement import CoordinateValue, MeasurementDatasetSchema
from scopecat.records.parameter import Quantity

RUN_PLAN_RECORD_SCHEMA_VERSION = "scopecat.run_plan_record.v8"
type _NonEmptyId = Annotated[str, Field(min_length=1)]
type RunPlanProducerKind = Literal["instrument", "domain", "host_transform"]
type RunPlanFusionMode = Literal["automatic", "disabled"]


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
    producer_kind: RunPlanProducerKind
    producer_unit_id: _NonEmptyId
    resource_port_id: _NonEmptyId | None = None
    physical_resource_id: _NonEmptyId | None = None
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
        if self.resource_port_id is not None and self.physical_resource_id is not None:
            msg = "run plan output cannot target both logical and physical resources"
            raise ValueError(msg)
        return self


class RunPlanChannelBinding(_RunPlanModel):
    entity_id: _NonEmptyId
    channel_id: _NonEmptyId
    line_id: _NonEmptyId | None = None
    capability: _NonEmptyId | None = None
    group_ids: list[_NonEmptyId] = Field(default_factory=list)


class RunPlanStateChange(_RunPlanModel):
    point_index: int = Field(ge=0)
    resource_id: _NonEmptyId
    resource_port_id: _NonEmptyId | None = None
    capability_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    before: RunPlanValue = None
    after: RunPlanValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[RunPlanChannelBinding] = Field(default_factory=list)

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"

    @model_validator(mode="after")
    def validate_values(self) -> RunPlanStateChange:
        _validate_run_plan_value(self.before, path="run plan state change before")
        _validate_run_plan_value(self.after, path="run plan state change after")
        if any(not entity_id for entity_id in self.entity_ids):
            msg = "run plan state change entity ids must be non-empty"
            raise ValueError(msg)
        if len(self.entity_ids) != len(set(self.entity_ids)):
            msg = "run plan state change entity ids must be unique"
            raise ValueError(msg)
        unbound = sorted(
            {
                binding.entity_id
                for binding in self.channel_bindings
                if binding.entity_id not in self.entity_ids
            }
        )
        if unbound:
            msg = (
                "run plan state change channel bindings reference entities outside "
                "the target: " + ", ".join(unbound)
            )
            raise ValueError(msg)
        self.before = cast("RunPlanValue", _normalize_entity_ref(self.before))
        self.after = cast("RunPlanValue", _normalize_entity_ref(self.after))
        return self


def _run_plan_channel_binding_identity(
    binding: RunPlanChannelBinding,
) -> tuple[str, str, str | None, str | None, tuple[str, ...]]:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        binding.capability,
        tuple(sorted(binding.group_ids)),
    )


def _run_plan_physical_channel_binding_identity(
    binding: RunPlanChannelBinding,
) -> tuple[str, str, str | None, tuple[str, ...]]:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        tuple(sorted(binding.group_ids)),
    )


def _run_plan_state_target_identity(
    change: RunPlanStateChange,
) -> tuple[object, ...]:
    return (
        change.point_index,
        change.resource_id,
        change.capability_id,
        change.field_path,
        tuple(change.entity_ids),
        tuple(
            _run_plan_channel_binding_identity(binding)
            for binding in change.channel_bindings
        ),
    )


class RunPlanResolvedRoute(_RunPlanModel):
    point_index: int = Field(ge=0)
    port_id: _NonEmptyId
    resource_id: _NonEmptyId
    resource_kind: _NonEmptyId
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    served_entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    product_axis_order: list[str] = Field(default_factory=list)
    channel_bindings: list[RunPlanChannelBinding] = Field(default_factory=list)


class RunPlanRoute(_RunPlanModel):
    port_id: _NonEmptyId
    capabilities: list[str] = Field(default_factory=list)
    entity_expr_count: int = Field(ge=0)
    fixed_resource_id: _NonEmptyId | None = None
    resolved: list[RunPlanResolvedRoute] = Field(default_factory=list)


class RunPlanFusionOptions(_RunPlanModel):
    """Durable user or planner bound on cross-point target fusion."""

    fusion: RunPlanFusionMode
    max_points_per_batch: Annotated[int, Field(ge=1)] | None

    @model_validator(mode="after")
    def validate_disabled_bound(self) -> RunPlanFusionOptions:
        if self.fusion == "disabled" and self.max_points_per_batch not in {None, 1}:
            msg = "disabled run-plan fusion cannot allow more than one point per batch"
            raise ValueError(msg)
        return self


class RunPlanExecutionOptions(_RunPlanModel):
    """Requested fusion policy and the concrete bound accepted by planning."""

    requested: RunPlanFusionOptions
    resolved: RunPlanFusionOptions

    @model_validator(mode="after")
    def validate_resolved_bound(self) -> RunPlanExecutionOptions:
        requested_limit = self.requested.max_points_per_batch
        resolved_limit = self.resolved.max_points_per_batch
        if self.resolved.fusion == "disabled" and resolved_limit != 1:
            msg = "resolved disabled run-plan fusion must have a one-point bound"
            raise ValueError(msg)
        if self.requested.fusion == "disabled" and self.resolved.fusion != "disabled":
            msg = "resolved run-plan fusion must preserve a disabled request"
            raise ValueError(msg)
        if requested_limit is not None and (
            resolved_limit is None or resolved_limit > requested_limit
        ):
            msg = "resolved run-plan fusion cannot exceed the requested point bound"
            raise ValueError(msg)
        return self


class RunPlanDomainCapabilities(_RunPlanModel):
    """Accepted point-batching limit of one domain-program adapter."""

    max_points_per_batch: Annotated[int, Field(ge=1)] | None


class RunPlanDomainBatch(_RunPlanModel):
    """Payload-free target identity for one selected logical-point batch."""

    batch_ordinal: int = Field(ge=0)
    point_indices: list[Annotated[int, Field(ge=0)]]
    semantic_operation_id: _NonEmptyId
    completion_contract: Literal["synchronous"]
    invocation_id: _NonEmptyId
    intent_fingerprint: _NonEmptyId
    target_id: _NonEmptyId
    compiler_id: _NonEmptyId
    capability_fingerprint: _NonEmptyId
    artifact_id: _NonEmptyId
    artifact_fingerprint: _NonEmptyId

    @model_validator(mode="after")
    def validate_point_indices(self) -> RunPlanDomainBatch:
        if not self.point_indices:
            msg = "run-plan domain batches require at least one logical point"
            raise ValueError(msg)
        if self.point_indices != sorted(set(self.point_indices)):
            msg = "run-plan domain batch point indices must be unique and ordered"
            raise ValueError(msg)
        return self


class RunPlanDomainExecution(_RunPlanModel):
    """One product-owning domain unit containing its physical invocations."""

    kind: Literal["domain_program"] = "domain_program"
    unit_id: _NonEmptyId
    adapter_id: _NonEmptyId
    semantic_operation_id: _NonEmptyId
    capabilities: RunPlanDomainCapabilities
    batches: list[RunPlanDomainBatch]

    @model_validator(mode="after")
    def validate_batches(self) -> RunPlanDomainExecution:
        ordinals = [batch.batch_ordinal for batch in self.batches]
        if ordinals != list(range(len(self.batches))):
            msg = "run-plan domain batch ordinals must be contiguous and ordered"
            raise ValueError(msg)
        maximum = self.capabilities.max_points_per_batch
        if maximum is not None and any(
            len(batch.point_indices) > maximum for batch in self.batches
        ):
            msg = "run-plan domain batch exceeds the adapter point capability"
            raise ValueError(msg)
        if any(
            batch.semantic_operation_id != self.semantic_operation_id
            for batch in self.batches
        ):
            msg = (
                "run-plan domain batches must retain their execution unit's "
                "semantic operation identity"
            )
            raise ValueError(msg)
        return self


class RunPlanPointInstrumentExecution(_RunPlanModel):
    """Accepted identity of the built-in point-at-a-time execution unit."""

    kind: Literal["point_instrument"] = "point_instrument"
    unit_id: _NonEmptyId
    backend_id: _NonEmptyId
    provider_id: _NonEmptyId
    submission_scope: Literal["point"] = "point"
    compute_placement: Literal["host"] = "host"


type RunPlanExecutionUnit = Annotated[
    RunPlanPointInstrumentExecution | RunPlanDomainExecution,
    Field(discriminator="kind"),
]


class RunPlanRecord(_RunPlanModel):
    """Stable projection of the plan accepted for one execution."""

    schema_version: Literal["scopecat.run_plan_record.v8"] = (
        RUN_PLAN_RECORD_SCHEMA_VERSION
    )
    backend_id: _NonEmptyId
    execution_options: RunPlanExecutionOptions
    experiment_id: str
    experiment_kind: str
    execution_units: list[RunPlanExecutionUnit] = Field(default_factory=list)
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
        self._validate_execution_units()
        self._validate_points()
        self._validate_point_references()
        self._validate_resource_references()
        self._validate_primary_observables()
        self._validate_expected_dataset_schema()
        self._validate_dataset_dimensions()
        return self

    def _validate_execution_units(self) -> None:
        units_by_id = {unit.unit_id: unit for unit in self.execution_units}
        if len(units_by_id) != len(self.execution_units):
            msg = "run plan execution unit IDs must be unique"
            raise ValueError(msg)
        if not self.execution_units:
            msg = "run plans require at least one execution unit"
            raise ValueError(msg)
        expected_point_indices = list(range(self.point_count))
        resolved_fusion = self.execution_options.resolved
        resolved_limit = (
            1
            if resolved_fusion.fusion == "disabled"
            else resolved_fusion.max_points_per_batch
        )
        domain_units = tuple(
            unit
            for unit in self.execution_units
            if isinstance(unit, RunPlanDomainExecution)
        )
        if not domain_units and (
            resolved_fusion.fusion != "disabled"
            or resolved_fusion.max_points_per_batch != 1
        ):
            msg = "run plans without domain units must resolve to pointwise execution"
            raise ValueError(msg)
        for unit in domain_units:
            covered = [
                point_index
                for batch in unit.batches
                for point_index in batch.point_indices
            ]
            if covered != expected_point_indices:
                msg = (
                    "run-plan domain batches must partition every logical point "
                    "exactly once in order"
                )
                raise ValueError(msg)
            if resolved_limit is not None and any(
                len(batch.point_indices) > resolved_limit for batch in unit.batches
            ):
                msg = "run-plan domain batch exceeds the resolved fusion point bound"
                raise ValueError(msg)
        for record in self.records:
            unit = units_by_id.get(record.producer_unit_id)
            if unit is None:
                msg = (
                    f"run plan output {record.id!r} references unknown producer unit "
                    f"{record.producer_unit_id!r}"
                )
                raise ValueError(msg)
            if record.producer_kind == "instrument" and not isinstance(
                unit, RunPlanPointInstrumentExecution
            ):
                msg = "instrument outputs require a point-instrument producer unit"
                raise ValueError(msg)
            if record.producer_kind != "instrument" and not isinstance(
                unit, RunPlanDomainExecution
            ):
                msg = "domain or host-transform outputs require a domain-program unit"
                raise ValueError(msg)

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

    def _validate_resource_references(self) -> None:
        routes_by_port = {route.port_id: route for route in self.routes}
        if len(routes_by_port) != len(self.routes):
            msg = "run plan route port IDs must be unique"
            raise ValueError(msg)
        expected_point_indices = list(range(self.point_count))
        for route in self.routes:
            resolved_point_indices = [
                resolved.point_index for resolved in route.resolved
            ]
            if resolved_point_indices != expected_point_indices:
                msg = (
                    f"run plan route {route.port_id!r} must resolve exactly once "
                    "for every point in order"
                )
                raise ValueError(msg)
            if any(resolved.port_id != route.port_id for resolved in route.resolved):
                msg = (
                    f"run plan route {route.port_id!r} resolved entries must retain "
                    "the same logical port ID"
                )
                raise ValueError(msg)
            for resolved in route.resolved:
                if len(resolved.entity_ids) != len(set(resolved.entity_ids)):
                    msg = "run plan resolved route entity ids must be unique"
                    raise ValueError(msg)
                if len(resolved.served_entity_ids) != len(
                    set(resolved.served_entity_ids)
                ):
                    msg = "run plan resolved route served entity ids must be unique"
                    raise ValueError(msg)
                if not set(resolved.entity_ids) <= set(resolved.served_entity_ids):
                    msg = (
                        "run plan resolved route entity ids must be served by the "
                        "physical resource"
                    )
                    raise ValueError(msg)
                target_entity_ids = {
                    *resolved.entity_ids,
                    *resolved.served_entity_ids,
                }
                if any(
                    binding.entity_id not in target_entity_ids
                    for binding in resolved.channel_bindings
                ):
                    msg = (
                        "run plan resolved route channel bindings must reference "
                        "served entities"
                    )
                    raise ValueError(msg)
                if any(
                    route.capabilities
                    and binding.capability is not None
                    and binding.capability not in route.capabilities
                    for binding in resolved.channel_bindings
                ):
                    msg = (
                        "run plan resolved route channel bindings must use a "
                        "capability provided by the logical resource port"
                    )
                    raise ValueError(msg)
            if route.fixed_resource_id is not None and any(
                resolved.resource_id != route.fixed_resource_id
                for resolved in route.resolved
            ):
                msg = (
                    f"run plan route {route.port_id!r} resolved entries must retain "
                    "the fixed physical resource ID"
                )
                raise ValueError(msg)
        for record in self.records:
            port_id = record.resource_port_id
            if port_id is None:
                continue
            route = routes_by_port.get(port_id)
            if route is None:
                msg = (
                    f"run plan output {record.id!r} references unknown logical "
                    f"resource port {port_id!r}"
                )
                raise ValueError(msg)
            if record.capability is not None and record.capability not in (
                route.capabilities
            ):
                msg = (
                    f"run plan output {record.id!r} capability "
                    f"{record.capability!r} is not provided by resource port "
                    f"{port_id!r}"
                )
                raise ValueError(msg)
            if any(
                resolved.resource_kind != "instrument" for resolved in route.resolved
            ):
                msg = (
                    f"run plan output {record.id!r} logical resource port must "
                    "resolve to instruments"
                )
                raise ValueError(msg)
        seen_state_targets: set[tuple[object, ...]] = set()
        for change in self.state_changes:
            target_identity = _run_plan_state_target_identity(change)
            if target_identity in seen_state_targets:
                msg = (
                    "run plan state changes must have unique physical targets "
                    "within each point"
                )
                raise ValueError(msg)
            seen_state_targets.add(target_identity)
            if any(
                binding.capability is not None
                and binding.capability != change.capability_id
                for binding in change.channel_bindings
            ):
                msg = (
                    "run plan state change channel binding capability must match "
                    "the state capability"
                )
                raise ValueError(msg)
            port_id = change.resource_port_id
            if port_id is None:
                continue
            route = routes_by_port.get(port_id)
            if route is None:
                msg = (
                    "run plan state change references unknown logical resource "
                    f"port {port_id!r}"
                )
                raise ValueError(msg)
            resolved = route.resolved[change.point_index]
            if resolved.resource_id != change.resource_id:
                msg = (
                    "run plan state change physical resource must equal its "
                    "logical route resolution"
                )
                raise ValueError(msg)
            if resolved.resource_kind != "instrument":
                msg = (
                    "run plan state change logical resource must resolve to an "
                    "instrument"
                )
                raise ValueError(msg)
            if change.capability_id not in route.capabilities:
                msg = (
                    "run plan state change capability is not provided by its "
                    "logical resource port"
                )
                raise ValueError(msg)
            allowed_entity_ids = set(resolved.entity_ids or resolved.served_entity_ids)
            if not set(change.entity_ids) <= allowed_entity_ids:
                msg = (
                    "run plan state change entities are outside its logical "
                    "route target"
                )
                raise ValueError(msg)
            route_bindings = {
                _run_plan_physical_channel_binding_identity(binding)
                for binding in resolved.channel_bindings
            }
            if (
                not {
                    _run_plan_physical_channel_binding_identity(binding)
                    for binding in change.channel_bindings
                }
                <= route_bindings
            ):
                msg = (
                    "run plan state change channel bindings are outside its "
                    "logical route target"
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
        for dimension in schema.dimensions:
            _validate_json_value(
                dimension.metadata,
                path=f"run plan dataset dimension {dimension.id!r} metadata",
            )
        for variable in schema.variables:
            _validate_json_value(
                variable.metadata,
                path=f"run plan dataset variable {variable.id!r} metadata",
            )
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
    "RunPlanDomainBatch",
    "RunPlanDomainCapabilities",
    "RunPlanDomainExecution",
    "RunPlanExecutionOptions",
    "RunPlanExecutionUnit",
    "RunPlanFusionMode",
    "RunPlanFusionOptions",
    "RunPlanOutput",
    "RunPlanPayloadValue",
    "RunPlanPoint",
    "RunPlanPointInstrumentExecution",
    "RunPlanProducerKind",
    "RunPlanRecord",
    "RunPlanResolvedRoute",
    "RunPlanRoute",
    "RunPlanStateChange",
]
