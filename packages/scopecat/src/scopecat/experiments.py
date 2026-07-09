"""Durable experiment spec and low-level experiment helpers.

The spec is intentionally small and mirrors the accepted linked IR shape:

``points -> params -> state -> records``

The transient planner lives in :mod:`scopecat._planning.planner`.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from scopecat._planning.parameter_patches import (
    ParameterPatchSpec,
)
from scopecat._planning.records import (
    RecordAxisPlan,
    RecordAxisSpec,
    RecordKind,
    RecordSource,
    RecordSpec,
)
from scopecat._planning.state import (
    StateRecord,
    StateSpec,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.parameter import (
    Quantity,
)
from scopecat.relations import (
    CellValue,
    ParameterRelationData,
    RelationExpr,
    Row,
    ScalarExpr,
    as_scalar_expr,
    col,
    grid,
    literal_rows,
    param,
)
from scopecat.relations import (
    linspace as relation_linspace,
)
from scopecat.relations import (
    table as parameter_table_relation,
)
from scopecat.relations import (
    values as relation_values,
)
from scopecat.results import (
    MeasurementDType,
)


class PointScanRecord(BaseModel):
    """Persisted point-value scan axis record."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["point"] = "point"
    target_id: str
    axis_id: str
    values: list[Any]
    unit: str | None = None
    input_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class AroundScanRecord(BaseModel):
    """Persisted center/span scan axis record."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scan"] = "scan"
    target_id: str
    axis_id: str
    center: Any
    span: Any
    points: int
    input_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ParameterScanRecord(BaseModel):
    """Persisted parameter-table scan axis record."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["parameter"] = "parameter"
    table_id: str
    key: Any
    column: str
    axis_id: str
    values: list[Any]
    unit: str | None = None


class ScanGroupRecord(BaseModel):
    """Persisted explicit scan composition record."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cartesian", "zip"]
    scans: list[ScanRecord]


type ScanLeafRecord = PointScanRecord | AroundScanRecord | ParameterScanRecord
type ScanRecord = Annotated[
    PointScanRecord | AroundScanRecord | ParameterScanRecord | ScanGroupRecord,
    Field(discriminator="kind"),
]
type ScanRecordLike = ScanRecord | Mapping[str, Any]

_SCAN_RECORD_ADAPTER: TypeAdapter[ScanRecord] = TypeAdapter(ScanRecord)
ScanGroupRecord.model_rebuild()


class RunRequest(BaseModel):
    """Operator request for one structured run segment."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_request.v1"
    id: str
    template_id: str | None = None
    template_inputs: dict[str, Any] = Field(default_factory=dict)
    config_source: str | None = None
    operator: str | None = None
    scans: list[ScanRecord] = Field(default_factory=list)
    segment_lineage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentSpec(BaseModel):
    """Closed structured experiment input for one run segment."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: str = "scopecat.experiment_spec.v3"
    id: str
    kind: str
    request: RunRequest | None = None
    config_snapshot_id: str | None = None
    points: RelationExpr
    route_intents: list[ResourceRouteIntent] = Field(default_factory=list)
    params: list[ParameterPatchSpec] = Field(default_factory=list)
    compute_nodes: list[ComputeNodeSpec] = Field(default_factory=list)
    state: list[StateSpec] = Field(default_factory=list)
    records: list[RecordSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


ComputeNodeFunction = Callable[..., object]


class ComputeNodeInput(BaseModel):
    """Input edge for a point-local pure compute node."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["value", "compute_result", "route"]
    value: ScalarExpr | None = None
    node_id: str | None = None
    port_id: str | None = None
    source_inputs: list[str] = Field(default_factory=list)

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
            return self
        if self.kind == "compute_result":
            if (
                self.node_id is None
                or self.value is not None
                or self.port_id is not None
            ):
                msg = "compute result input requires node_id only"
                raise ValueError(msg)
            return self
        if self.port_id is None or self.value is not None or self.node_id is not None:
            msg = "route compute node input requires port_id only"
            raise ValueError(msg)
        return self


class ComputeNodeSpec(BaseModel):
    """Runtime-lowered pure code island declared by authoring modules."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    inputs: dict[str, ComputeNodeInput] = Field(default_factory=dict)
    route_ports: list[str] = Field(default_factory=list)
    fn: ComputeNodeFunction | None = Field(default=None, exclude=True)


@dataclass(frozen=True)
class ComputeNodeContext:
    """Point-local inputs supplied to context-style compute functions."""

    node_id: str
    point_index: int
    point_uid: str
    row: Row
    params: ParameterRelationData
    inputs: Mapping[str, object]
    routes: tuple[PointRouteBinding, ...]
    payloads: Mapping[str, CommandPayload]

    def scalar(self, parameter_id: str) -> CellValue:
        return self.params.scalar(parameter_id)

    def route(self, port_id: str) -> PointRouteBinding:
        for binding in self.routes:
            if binding.port_id == port_id:
                return binding
        msg = f"compute node {self.node_id!r} has no route binding for {port_id!r}"
        raise KeyError(msg)


class ProductBinding(BaseModel):
    """Runtime mapping from a device-local product to an experiment record."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    record_id: str
    instrument_id: str | None = None
    product_key: str
    kind: RecordKind
    capability: str | None = None
    unit: str | None = None
    dtype: MeasurementDType
    axes: list[RecordAxisPlan] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceRouteIntent(BaseModel):
    """Symbolic resource route preserved until point-local program compilation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    port_id: str
    capabilities: list[str] = Field(default_factory=list)
    entity_exprs: list[ScalarExpr] = Field(default_factory=list)
    resource_id: str | None = None


class PointRouteBinding(BaseModel):
    """Concrete route selected for one point program."""

    model_config = ConfigDict(extra="forbid")

    port_id: str
    resource_id: str
    capabilities: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    product_axis_order: list[str] = Field(default_factory=list)
    channel_bindings: list[RoutingChannelBinding] = Field(default_factory=list)


class ProgramStateValue(BaseModel):
    """Device-program state value before conversion to driver SDK commands."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["quantity", "number", "payload"]
    quantity: Quantity | None = None
    value: float | None = None
    payload_id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ProgramStateValue:
        if self.kind == "quantity":
            if self.quantity is None:
                msg = "quantity program state value requires quantity"
                raise ValueError(msg)
            if self.value is not None or self.payload_id is not None:
                msg = "quantity program state value cannot contain value or payload_id"
                raise ValueError(msg)
            return self
        if self.kind == "number":
            if self.value is None:
                msg = "number program state value requires value"
                raise ValueError(msg)
            if self.quantity is not None or self.payload_id is not None:
                msg = "number program state value cannot contain quantity or payload_id"
                raise ValueError(msg)
            return self
        if self.payload_id is None:
            msg = "payload program state value requires payload_id"
            raise ValueError(msg)
        if self.quantity is not None or self.value is not None:
            msg = "payload program state value cannot contain quantity or value"
            raise ValueError(msg)
        return self


class ProgramStateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: ProgramStateValue
    channel_bindings: list[RoutingChannelBinding] = Field(default_factory=list)


class ProgramResourceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    fields: list[ProgramStateField] = Field(default_factory=list)


class CollectInstructionPlan(BaseModel):
    """Runtime collection request for one point and one logical instrument."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    instrument_id: str | None = None
    products: list[ProductBinding] = Field(default_factory=list)


@dataclass(frozen=True)
class ParameterRowSelector:
    """Authoring selector for one parameter-table row."""

    table_id: str
    key: dict[str, object]

    def value(self, column: str) -> ScalarExpr:
        return param(self.table_id, key=self.key, column=column)

    def patch(self, **values: object) -> ParameterPatchSpec:
        return update_param_rows(self.table_id, key=self.key, values=values)


@dataclass(frozen=True)
class ScanAxis:
    """Point axis used by template defaults, invocations, and scratch experiments."""

    target_id: str
    axis_id: str
    point_values: tuple[object, ...] = ()
    unit: str | None = None
    center: ScalarExpr | None = None
    span: object | None = None
    point_count: int | None = None
    input_id: str | None = None
    implicit_center: bool = False

    @property
    def points(self) -> RelationExpr:
        if self.point_values:
            source = (
                relation_values(self.point_values, unit=self.unit)
                if self.unit is not None
                else list(self.point_values)
            )
            return grid(**{self.axis_id: source})
        if self.center is None or self.span is None or self.point_count is None:
            msg = f"scan axis {self.axis_id!r} requires values or center/span/points"
            raise ValueError(msg)
        if self.point_count < 2:
            msg = "scan axis points must be at least 2"
            raise ValueError(msg)
        span = _scan_quantity(self.span)
        return grid(
            **{
                self.axis_id: relation_linspace(
                    self.center - span / 2,
                    self.center + span / 2,
                    self.point_count,
                )
            }
        )

    def request_record(self) -> PointScanRecord | AroundScanRecord:
        if self.point_values:
            return PointScanRecord(
                target_id=self.target_id,
                axis_id=self.axis_id,
                values=[_request_value(value) for value in self.point_values],
                unit=self.unit,
                input_id=self.input_id,
            )
        if self.center is None or self.span is None or self.point_count is None:
            msg = f"scan axis {self.axis_id!r} requires values or center/span/points"
            raise ValueError(msg)
        return AroundScanRecord(
            target_id=self.target_id,
            axis_id=self.axis_id,
            center=_request_value(self.center),
            span=_request_value(self.span),
            points=self.point_count,
            input_id=self.input_id,
        )

    def values_axis(
        self,
        values: Sequence[object],
        *,
        unit: str | None = None,
    ) -> ScanAxis:
        return axis(
            self.axis_id,
            values=values,
            unit=unit,
            target_id=self.target_id,
            input_id=self.input_id,
        )

    def values(
        self,
        values: Sequence[object],
        *,
        unit: str | None = None,
    ) -> ScanAxis:
        return self.values_axis(values, unit=unit)

    def around_active(
        self,
        *,
        span: object,
        points: int,
    ) -> ScanAxis:
        return self.around(center=param(self.target_id), span=span, points=points)

    def around(
        self,
        *,
        center: ScalarExpr,
        span: object,
        points: int,
    ) -> ScanAxis:
        return ScanAxis(
            target_id=self.target_id,
            axis_id=self.axis_id,
            center=center,
            span=span,
            point_count=points,
            input_id=self.input_id,
        )


@dataclass(frozen=True)
class ParameterScanAxis:
    """Parameter-table scan lowered into point-local patches."""

    table_id: str
    key: dict[str, object]
    column: str
    axis_id: str
    values: tuple[object, ...]
    unit: str | None = None

    @property
    def points(self) -> RelationExpr:
        source = (
            relation_values(self.values, unit=self.unit)
            if self.unit is not None
            else list(self.values)
        )
        return grid(**{self.axis_id: source})

    def request_record(self) -> ParameterScanRecord:
        return ParameterScanRecord(
            table_id=self.table_id,
            key=_request_value(self.key),
            column=self.column,
            axis_id=self.axis_id,
            values=[_request_value(value) for value in self.values],
            unit=self.unit,
        )


@dataclass(frozen=True)
class ScanGroup:
    """Explicit scan-axis composition."""

    kind: Literal["cartesian", "zip"]
    scans: tuple[ScanItem, ...]

    @property
    def points(self) -> RelationExpr:
        if self.kind == "cartesian":
            return _cartesian_scan_points(self.scans)
        return _zip_scan_points(self.scans)

    def request_record(self) -> ScanGroupRecord:
        return ScanGroupRecord(
            kind=self.kind,
            scans=[scan.request_record() for scan in self.scans],
        )


type ScanLeaf = ScanAxis | ParameterScanAxis
type ScanItem = ScanAxis | ParameterScanAxis | ScanGroup


def axis(
    axis_id: str,
    values: Sequence[object] = (),
    *,
    unit: str | None = None,
    center: ScalarExpr | None = None,
    span: object | None = None,
    points: int | None = None,
    target_id: str | None = None,
    input_id: str | None = None,
) -> ScanAxis:
    if not axis_id:
        msg = "scan axis id must be non-empty"
        raise ValueError(msg)
    if values and (center is not None or span is not None or points is not None):
        msg = "scan axis accepts either values or center/span/points, not both"
        raise ValueError(msg)
    if (
        not values
        and any(item is not None for item in (center, span, points))
        and (center is None or span is None or points is None)
    ):
        msg = "scan axis around form requires center, span, and points"
        raise ValueError(msg)
    return ScanAxis(
        target_id=target_id or axis_id,
        axis_id=axis_id,
        point_values=tuple(values),
        unit=unit,
        center=center,
        span=span,
        point_count=points,
        input_id=input_id,
    )


def param_axis(
    row: ParameterRowSelector,
    column: str,
    values: Sequence[object],
    *,
    axis_id: str | None = None,
    unit: str | None = None,
) -> ParameterScanAxis:
    if not column:
        msg = "parameter scan column must be non-empty"
        raise ValueError(msg)
    if not values:
        msg = "parameter scan values must contain at least one value"
        raise ValueError(msg)
    return ParameterScanAxis(
        table_id=row.table_id,
        key=dict(row.key),
        column=column,
        axis_id=axis_id or column,
        values=tuple(values),
        unit=unit,
    )


def cartesian(*scans: ScanItem) -> ScanGroup:
    if not scans:
        msg = "cartesian scan group requires at least one scan"
        raise ValueError(msg)
    return ScanGroup(kind="cartesian", scans=tuple(scans))


def zip(*scans: ScanItem) -> ScanGroup:  # noqa: A001
    if not scans:
        msg = "zip scan group requires at least one scan"
        raise ValueError(msg)
    return ScanGroup(kind="zip", scans=tuple(scans))


def iter_scan_leaves(
    scan: ScanItem,
) -> tuple[ScanLeaf, ...]:
    if isinstance(scan, ScanGroup):
        return tuple(leaf for child in scan.scans for leaf in iter_scan_leaves(child))
    return (scan,)


def scan_axis_index(
    scans: Sequence[ScanRecordLike],
) -> dict[str, ScanLeafRecord]:
    """Return a flat axis_id index derived from canonical scan records."""

    axes: dict[str, ScanLeafRecord] = {}
    for scan in scans:
        for leaf in _scan_record_leaves(scan):
            axes[leaf.axis_id] = leaf
    return axes


def parameter_scan_records(
    scans: Sequence[ScanRecordLike],
) -> list[ParameterScanRecord]:
    """Return parameter-scan leaves derived from canonical scan records."""

    return [
        leaf
        for scan in scans
        for leaf in _scan_record_leaves(scan)
        if isinstance(leaf, ParameterScanRecord)
    ]


def _scan_record_leaves(scan: ScanRecordLike) -> tuple[ScanLeafRecord, ...]:
    typed_scan = _coerce_scan_record(scan)
    if not isinstance(typed_scan, ScanGroupRecord):
        return (typed_scan,)
    return tuple(
        leaf for child in typed_scan.scans for leaf in _scan_record_leaves(child)
    )


def _coerce_scan_record(scan: ScanRecordLike) -> ScanRecord:
    if isinstance(
        scan,
        PointScanRecord | AroundScanRecord | ParameterScanRecord | ScanGroupRecord,
    ):
        return scan
    return _SCAN_RECORD_ADAPTER.validate_python(scan)


def _cartesian_scan_points(scans: Sequence[ScanItem]) -> RelationExpr:
    relation = scans[0].points
    for next_scan in scans[1:]:
        relation = relation.cross(next_scan.points)
    return relation


def _zip_scan_points(scans: Sequence[ScanItem]) -> RelationExpr:
    rows_by_scan = [_scan_rows(scan) for scan in scans]
    lengths = {len(rows) for rows in rows_by_scan}
    if len(lengths) != 1:
        msg = "zip scan group requires scans with equal length"
        raise ValueError(msg)
    rows: list[Row] = []
    for row_group in builtins.zip(*rows_by_scan, strict=True):
        merged: Row = {}
        for row in row_group:
            overlap = set(merged).intersection(row)
            if overlap:
                msg = "zip scan group contains duplicate axes: " + ", ".join(
                    sorted(overlap)
                )
                raise ValueError(msg)
            merged.update(row)
        rows.append(merged)
    return literal_rows(rows)


def _scan_rows(scan: ScanItem) -> list[Row]:
    return scan.points.evaluate()


def _scan_quantity(value: object) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if isinstance(value, str):
        import re

        match = re.match(
            r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([A-Za-z][A-Za-z0-9_]*)\s*$",
            value,
        )
        if match is not None:
            return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = "scan span must be a Quantity or '<number> <unit>' string"
    raise TypeError(msg)


@dataclass(frozen=True)
class LocalOverrides:
    """Authoring fragment for resource-local override axes and desired state."""

    points: RelationExpr
    state: list[StateSpec]


def rows(table_id: str, **where: object) -> RelationExpr:
    relation = parameter_table_relation(table_id)
    for column_id, value in where.items():
        relation = relation.filter(col(column_id).eq(value))
    return relation


def param_row(table_id: str, **key: object) -> ParameterRowSelector:
    return ParameterRowSelector(table_id=table_id, key=dict(key))


def configure(*params: ParameterPatchSpec) -> list[ParameterPatchSpec]:
    return list(params)


def _request_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _request_value(asdict(value))
    if isinstance(value, dict):
        mapping = cast("dict[Any, object]", value)
        return {str(key): _request_value(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return [_request_value(item) for item in sequence]
    return value


def local_overrides(
    field: str,
    values_by_resource: dict[str, object],
    *,
    axis_prefix: str = "local",
) -> LocalOverrides:
    axes: dict[str, object] = {}
    state: list[StateSpec] = []
    for resource, source in values_by_resource.items():
        axis_id = _axis_name(axis_prefix, resource)
        if axis_id in axes:
            msg = f"duplicate local override axis {axis_id!r}"
            raise ValueError(msg)
        axes[axis_id] = source
        state.append(set_state(resource, field, col(axis_id)))
    return LocalOverrides(points=grid(**axes), state=state)


def local_scan(
    axis: str,
    *,
    center: object,
    offsets: object,
    center_axis: str | None = None,
    offset_axis: str | None = None,
) -> RelationExpr:
    center_id = center_axis or f"{axis}_center"
    offset_id = offset_axis or f"{axis}_offset"
    return grid(**{center_id: center, offset_id: offsets}).with_columns(
        **{axis: col(center_id) + col(offset_id)}
    )


def set_param(parameter_id: str, value: object) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="set_scalar",
        parameter_id=parameter_id,
        value=as_scalar_expr(value),
    )


def update_param_rows(
    table_id: str,
    *,
    key: dict[str, object],
    values: dict[str, object],
) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="update_rows",
        table_id=table_id,
        key={name: as_scalar_expr(value) for name, value in key.items()},
        values={name: as_scalar_expr(value) for name, value in values.items()},
    )


def insert_param_rows(
    table_id: str,
    rows: list[dict[str, object]],
) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="insert_rows",
        table_id=table_id,
        rows=[
            {name: as_scalar_expr(value) for name, value in row.items()} for row in rows
        ],
    )


def delete_param_rows(
    table_id: str,
    *,
    key: dict[str, object],
) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="delete_rows",
        table_id=table_id,
        key={name: as_scalar_expr(value) for name, value in key.items()},
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
        value=as_scalar_expr(value),
        route_entities=[as_scalar_expr(entity) for entity in route_entities],
    )


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


def experiment(
    *,
    id: str,  # noqa: A002
    kind: str,
    points: RelationExpr,
    params: list[ParameterPatchSpec] | None = None,
    state: list[StateSpec] | None = None,
    records: list[RecordSpec] | None = None,
) -> ExperimentSpec:
    return ExperimentSpec(
        id=id,
        kind=kind,
        points=points,
        params=params or [],
        state=state or [],
        records=records or [],
    )


def _axis_name(prefix: str, resource: str) -> str:
    suffix = "".join(char if char.isalnum() else "_" for char in resource).strip("_")
    if suffix == "":
        msg = f"resource {resource!r} cannot produce a local override axis"
        raise ValueError(msg)
    return f"{prefix}_{suffix}"


ExperimentSpec.model_rebuild()

__all__ = [
    "AroundScanRecord",
    "ExperimentSpec",
    "LocalOverrides",
    "ParameterPatchSpec",
    "ParameterRowSelector",
    "ParameterScanAxis",
    "ParameterScanRecord",
    "PointScanRecord",
    "RecordAxisSpec",
    "RecordKind",
    "RecordSource",
    "RecordSpec",
    "ResourceRouteIntent",
    "ScanAxis",
    "ScanGroup",
    "ScanGroupRecord",
    "ScanItem",
    "ScanLeaf",
    "ScanLeafRecord",
    "ScanRecord",
    "StateRecord",
    "StateSpec",
    "axis",
    "bind_each",
    "cartesian",
    "configure",
    "delete_param_rows",
    "experiment",
    "insert_param_rows",
    "local_overrides",
    "local_scan",
    "observable",
    "param_axis",
    "param_row",
    "parameter_scan_records",
    "record_axis",
    "record_output",
    "rows",
    "scan_axis_index",
    "set_param",
    "set_state",
    "shot_axis",
    "update_param_rows",
    "zip",
]
