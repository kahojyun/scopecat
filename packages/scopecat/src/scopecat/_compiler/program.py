"""Transient linked program produced by the authoring compiler.

Nothing in this module is a durable wire format. ``LinkedProgram`` is passed
directly from authoring resolution to planning/runtime lowering and deliberately
has no schema version or round-trip compatibility promise.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat._compiler.parameter_overlays import (
    PointParameterOverlay,
    TypedOverlayExpression,
)
from scopecat._compute_result import ComputeResultRef
from scopecat._planning.records import (
    RecordAxisSpec,
    RecordKind,
    RecordSource,
    RecordSpec,
)
from scopecat._planning.state import (
    StateSpec,
    as_state_route_value_expr,
)
from scopecat._relations import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat._value_expressions import (
    ScalarOrSeriesValueExpr,
    ValueExpr,
    as_scalar_or_series_value_expr,
    as_value_expr,
)
from scopecat.results import MeasurementDType
from scopecat.value_types import Route, Scalar, ValueType

ComputeNodeFunction = Callable[..., object]

type ComputeNodeOutputType = ValueType


class ComputeNodeInput(BaseModel):
    """Input edge for a point-local pure compute node."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["value", "compute_result", "route"]
    value: ValueExpr | None = None
    node_id: str | None = None
    port_id: str | None = None
    source_inputs: list[str] = Field(default_factory=list)
    value_type: ValueType | Route

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value_expression(cls, value: object) -> object:
        if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
            return as_value_expr(value)
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> ComputeNodeInput:
        if self.kind == "value":
            if (
                self.value is None
                or self.node_id is not None
                or self.port_id is not None
            ):
                msg = "value compute node input requires value only"
                raise ValueError(msg)
            if isinstance(self.value_type, Route):
                msg = "value compute node input requires a value type"
                raise ValueError(msg)
            return self
        if self.kind == "compute_result":
            if (
                self.node_id is None
                or self.value is not None
                or self.port_id is not None
            ):
                msg = "compute result input requires node_id only"
                raise ValueError(msg)
            if isinstance(self.value_type, Route):
                msg = "compute result input requires a value type"
                raise ValueError(msg)
            return self
        if self.port_id is None or self.value is not None or self.node_id is not None:
            msg = "route compute node input requires port_id only"
            raise ValueError(msg)
        if not isinstance(self.value_type, Route):
            msg = "route compute node input requires a route type"
            raise ValueError(msg)
        return self


class ComputeNodeSpec(BaseModel):
    """Runtime-lowered pure code island declared by an authoring module."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    inputs: dict[str, ComputeNodeInput] = Field(default_factory=dict)
    output_type: ComputeNodeOutputType
    fn: ComputeNodeFunction | None = Field(default=None, exclude=True)


class ResourceRouteIntent(BaseModel):
    """Symbolic resource route retained until point-local compilation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    port_id: str
    capabilities: list[str] = Field(default_factory=list)
    entity_exprs: list[ScalarOrSeriesValueExpr] = Field(default_factory=list)
    resource_id: str | None = None

    @field_validator("entity_exprs", mode="before")
    @classmethod
    def coerce_entity_expressions(cls, value: object) -> object:
        if isinstance(value, list | tuple):
            items = cast("Sequence[object]", value)
            return [
                as_scalar_or_series_value_expr(item)
                if isinstance(item, ScalarExpr | SeriesExpr)
                else item
                for item in items
            ]
        return value


class LinkedProgram(BaseModel):
    """Closed, transient compiler output for one run segment."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    kind: str
    points: RelationExpr
    route_intents: list[ResourceRouteIntent] = Field(default_factory=list)
    parameter_overlays: list[PointParameterOverlay] = Field(default_factory=list)
    compute_nodes: list[ComputeNodeSpec] = Field(default_factory=list)
    state: list[StateSpec] = Field(default_factory=list)
    records: list[RecordSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def overlay_parameter_cell(
    table_id: str,
    *,
    key: dict[str, object],
    key_types: dict[str, Scalar],
    column_id: str,
    value: object,
    value_type: Scalar,
) -> PointParameterOverlay:
    """Build a typed point-local cell overlay for internal compiler tests."""

    if set(key) != set(key_types):
        msg = "parameter overlay key and key_types must contain the same columns"
        raise ValueError(msg)
    return PointParameterOverlay(
        table_id=table_id,
        key={
            name: TypedOverlayExpression(
                expr=as_scalar_expr(expression),
                value_type=key_types[name],
            )
            for name, expression in key.items()
        },
        column_id=column_id,
        value=TypedOverlayExpression(
            expr=as_scalar_expr(value),
            value_type=value_type,
        ),
    )


def set_state(
    resource: object,
    field: str,
    value: object,
    *,
    route_entities: Sequence[object] = (),
) -> StateSpec:
    return StateSpec(
        kind="set",
        resource=as_scalar_expr(resource),
        field=field,
        value=value if isinstance(value, ComputeResultRef) else as_scalar_expr(value),
        route_entities=[as_state_route_value_expr(entity) for entity in route_entities],
    )


def compute_result(node_id: str) -> ComputeResultRef:
    """Reference one point-local compute result."""

    return ComputeResultRef(node_id=node_id)


def bind_each(relation: RelationExpr, *state: StateSpec) -> StateSpec:
    return StateSpec(kind="for_each", relation=relation, state=list(state))


def record_axis(
    id: str,  # noqa: A002
    *,
    size: int,
    kind: str | None = None,
    unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RecordAxisSpec:
    return RecordAxisSpec(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=dict(metadata or {}),
    )


def shot_axis(size: int) -> RecordAxisSpec:
    return record_axis("shot", size=size, kind="shot", unit="count")


def record_output(
    id: str,  # noqa: A002
    *,
    kind: RecordKind = "observable",
    source: RecordSource = "instrument",
    unit: str | None = None,
    resource: str | None = None,
    capability: str | None = None,
    product_key: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: list[RecordAxisSpec] | None = None,
) -> RecordSpec:
    return RecordSpec(
        id=id,
        kind=kind,
        source=source,
        resource=resource,
        capability=capability,
        product_key=product_key,
        unit=unit,
        dtype=dtype,
        axes=axes or [],
    )


def observable(
    id: str,  # noqa: A002
    *,
    source: RecordSource = "instrument",
    unit: str | None = None,
    resource: str | None = None,
    capability: str | None = None,
    product_key: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: list[RecordAxisSpec] | None = None,
) -> RecordSpec:
    return record_output(
        id,
        kind="observable",
        source=source,
        unit=unit,
        resource=resource,
        capability=capability,
        product_key=product_key,
        dtype=dtype,
        axes=axes,
    )


def linked_program(
    *,
    id: str,  # noqa: A002
    kind: str,
    points: RelationExpr,
    parameter_overlays: list[PointParameterOverlay] | None = None,
    state: list[StateSpec] | None = None,
    records: list[RecordSpec] | None = None,
) -> LinkedProgram:
    """Build a low-level linked program for internal tests and compiler code."""

    return LinkedProgram(
        id=id,
        kind=kind,
        points=points,
        parameter_overlays=parameter_overlays or [],
        state=state or [],
        records=records or [],
    )


__all__ = [
    "ComputeNodeFunction",
    "ComputeNodeInput",
    "ComputeNodeOutputType",
    "ComputeNodeSpec",
    "LinkedProgram",
    "ResourceRouteIntent",
    "bind_each",
    "compute_result",
    "linked_program",
    "observable",
    "overlay_parameter_cell",
    "record_axis",
    "record_output",
    "set_state",
    "shot_axis",
]
