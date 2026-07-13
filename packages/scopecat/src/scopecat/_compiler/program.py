"""Typed transient program produced by the authoring compiler.

Nothing in this module is a durable wire format. ``TypedProgram`` retains the
typed point source and explicit dataflow edges needed by later compiler passes,
and deliberately has no schema version or round-trip compatibility promise.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from scopecat._compiler.ids import NodeId
from scopecat._compiler.parameter_overlays import (
    PointParameterOverlay,
    TypedOverlayExpression,
)
from scopecat._compiler.records import (
    RecordAxisSpec,
    RecordKind,
    RecordSource,
    RecordSpec,
)
from scopecat._compiler.state import (
    StateSpec,
    as_state_route_value_expr,
)
from scopecat._compute_result import ComputeResultRef
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
from scopecat.value_types import Route, Scalar, Table, ValueType


class ValueInput(BaseModel):
    """Typed expression evaluated for one compute invocation."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["value"] = "value"
    value: ValueExpr
    source_inputs: tuple[str, ...] = ()
    value_type: ValueType

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value_expression(cls, value: object) -> object:
        if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
            return as_value_expr(value)
        return value


class ComputeEdge(BaseModel):
    """Explicit dependency on the result of another compute node."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["compute"] = "compute"
    producer: NodeId
    value_type: ValueType


class RouteInput(BaseModel):
    """Explicit dependency on a point-local resolved resource route."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["route"] = "route"
    port_id: str
    value_type: Route


type ComputeInput = Annotated[
    ValueInput | ComputeEdge | RouteInput,
    Field(discriminator="kind"),
]


class TypedComputeNode(BaseModel):
    """One typed pure-code node in the expanded compute graph."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: NodeId
    inputs: dict[str, ComputeInput] = Field(default_factory=dict)
    output_type: ValueType
    fn: Callable[..., object] | None = Field(default=None, exclude=True)


class ResourceRouteIntent(BaseModel):
    """Symbolic resource route retained until point-local compilation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    port_id: str
    capabilities: tuple[str, ...] = ()
    entity_exprs: tuple[ScalarOrSeriesValueExpr, ...] = ()
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


class TypedPointSource(BaseModel):
    """Bound but unevaluated point relation with its semantic table type."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    expr: RelationExpr
    value_type: Table
    entity_column_ids: tuple[str, ...] = ()


class TypedProgram(BaseModel):
    """Closed typed compiler output for one run segment."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str
    kind: str
    point_source: TypedPointSource
    route_intents: tuple[ResourceRouteIntent, ...] = ()
    parameter_overlays: tuple[PointParameterOverlay, ...] = ()
    compute_nodes: tuple[TypedComputeNode, ...] = ()
    state: tuple[StateSpec, ...] = ()
    records: tuple[RecordSpec, ...] = ()
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


def set_state_field(
    resource: object,
    *,
    capability_id: str,
    field_path: str,
    value: object,
    route_entities: Sequence[object] = (),
) -> StateSpec:
    """Build desired state from orthogonal capability and field identities."""

    return StateSpec(
        kind="set",
        resource=as_scalar_expr(resource),
        capability_id=capability_id,
        field_path=field_path,
        value=value if isinstance(value, ComputeResultRef) else as_scalar_expr(value),
        route_entities=[as_state_route_value_expr(entity) for entity in route_entities],
    )


def compute_result(node_id: NodeId | str) -> ComputeResultRef:
    """Reference one point-local compute result."""

    selected = node_id if isinstance(node_id, NodeId) else NodeId(local_id=node_id)
    return ComputeResultRef(node_id=selected)


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


def typed_program(
    *,
    id: str,  # noqa: A002
    kind: str,
    point_source: TypedPointSource,
    route_intents: Sequence[ResourceRouteIntent] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[TypedComputeNode] = (),
    state: Sequence[StateSpec] = (),
    records: Sequence[RecordSpec] = (),
    metadata: dict[str, Any] | None = None,
) -> TypedProgram:
    """Build and verify one low-level typed program."""

    from scopecat._compiler.graph import order_compute_nodes

    return TypedProgram(
        id=id,
        kind=kind,
        point_source=point_source,
        route_intents=tuple(route_intents),
        parameter_overlays=tuple(parameter_overlays),
        compute_nodes=order_compute_nodes(compute_nodes),
        state=tuple(state),
        records=tuple(records),
        metadata=dict(metadata or {}),
    )


__all__ = [
    "ComputeEdge",
    "ComputeInput",
    "ResourceRouteIntent",
    "RouteInput",
    "TypedComputeNode",
    "TypedPointSource",
    "TypedProgram",
    "ValueInput",
    "bind_each",
    "compute_result",
    "observable",
    "overlay_parameter_cell",
    "record_axis",
    "record_output",
    "set_state_field",
    "shot_axis",
    "typed_program",
]
