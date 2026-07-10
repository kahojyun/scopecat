from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat._planning.diagnostics import planning_diagnostic
from scopecat._relations import CellValue, Row
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.results import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementVariable,
)
from scopecat.units import compatible_units

RecordKind = Literal["observable", "artifact", "readback", "expression"]
RecordSource = Literal["instrument", "state", "point", "expression", "runtime"]


class RecordAxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int = Field(gt=0)
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordSpec(BaseModel):
    """Closed logical output declaration for one run segment."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: RecordKind = "observable"
    source: RecordSource = "instrument"
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: list[RecordAxisSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordAxisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: RecordKind
    source: RecordSource
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType
    axes: list[RecordAxisPlan] = Field(default_factory=list)
    dims: list[str] = Field(default_factory=list)
    shape: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PointRecordLike(Protocol):
    @property
    def row(self) -> Row: ...


def plan_records(
    records: Sequence[RecordSpec],
    *,
    point_count: int,
) -> list[RecordPlan]:
    return [
        RecordPlan(
            id=record.id,
            kind=record.kind,
            source=record.source,
            resource=record.resource,
            capability=record.capability,
            product_key=record.product_key,
            unit=record.unit,
            dtype=record.dtype,
            axes=[
                RecordAxisPlan(
                    id=axis.id,
                    kind=axis.kind,
                    size=axis.size,
                    unit=axis.unit,
                    metadata=axis.metadata,
                )
                for axis in record.axes
            ],
            dims=["point", *(axis.id for axis in record.axes)],
            shape=[point_count, *(axis.size for axis in record.axes)],
            metadata=record.metadata,
        )
        for record in records
    ]


def validate_record_plan(records: Sequence[RecordPlan]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    record_ids = [record.id for record in records]
    duplicate_record_ids = _duplicates(record_ids)
    for record_id in sorted(duplicate_record_ids):
        diagnostics.append(
            planning_diagnostic(
                "error",
                "experiment_record_duplicate",
                f"experiment record {record_id!r} is duplicated",
                "records",
            )
        )
    for record in records:
        axis_ids = [axis.id for axis in record.axes]
        for axis_id in sorted(_duplicates(axis_ids)):
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_record_axis_duplicate",
                    f"record {record.id!r} axis {axis_id!r} is duplicated",
                    f"records.{record.id}.axes",
                )
            )
        if record.kind != "observable":
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_record_kind_unsupported",
                    f"record kind {record.kind!r} is not supported yet",
                    f"records.{record.id}.kind",
                )
            )
    product_keys_by_resource: dict[str | None, list[str]] = {}
    for record in records:
        if record.source != "instrument" or record.kind != "observable":
            continue
        if record.id in duplicate_record_ids:
            continue
        product_keys_by_resource.setdefault(record.resource, []).append(
            _record_product_key(record)
        )
    for resource, product_keys in product_keys_by_resource.items():
        for product_key in sorted(_duplicates(product_keys)):
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_record_product_duplicate",
                    f"instrument product {product_key!r} is mapped more than once",
                    "records" if resource is None else f"records.{resource}",
                )
            )
    return diagnostics


def expected_dataset_schema(
    *,
    experiment_id: str,
    points: Sequence[PointRecordLike],
    records: Sequence[RecordPlan],
    dataset_id: str = "raw-measurements",
) -> MeasurementDatasetSchema | None:
    observable_records = [record for record in records if record.kind == "observable"]
    if not points or not observable_records:
        return None
    dimensions = [
        MeasurementDimension(id="point", kind="point", size=len(points)),
        *_record_axes(observable_records),
    ]
    coordinates = _coordinate_variables(points)
    observables = [
        MeasurementVariable(
            id=record.id,
            role="observable",
            dtype=record.dtype,
            unit=record.unit,
            dims=record.dims,
            shape=record.shape,
            metadata={
                "source": record.source,
                **({"resource": record.resource} if record.resource else {}),
                **({"capability": record.capability} if record.capability else {}),
                **({"product_key": record.product_key} if record.product_key else {}),
                **record.metadata,
            },
        )
        for record in observable_records
    ]
    return MeasurementDatasetSchema(
        dataset_id=dataset_id,
        dataset_role="raw",
        dimensions=dimensions,
        variables=[*coordinates, *observables],
        primary_coordinates=[variable.id for variable in coordinates],
        primary_observables=[record.id for record in observable_records],
        metadata={"experiment_id": experiment_id},
    )


def point_coordinate_ids(points: Sequence[PointRecordLike]) -> list[str]:
    return [variable.id for variable in _coordinate_variables(points)]


def _record_axes(records: Sequence[RecordPlan]) -> list[MeasurementDimension]:
    dimensions: list[MeasurementDimension] = []
    seen: dict[str, RecordAxisPlan] = {}
    for record in records:
        for axis in record.axes:
            existing = seen.get(axis.id)
            if existing is not None:
                continue
            seen[axis.id] = axis
            dimensions.append(
                MeasurementDimension(
                    id=axis.id,
                    kind=axis.kind,
                    size=axis.size,
                    unit=axis.unit,
                    metadata=axis.metadata,
                )
            )
    return dimensions


def _record_product_key(record: RecordPlan) -> str:
    if record.product_key:
        return record.product_key
    if record.capability:
        return record.capability
    return record.id


def _coordinate_variables(
    points: Sequence[PointRecordLike],
) -> list[MeasurementVariable]:
    variables: list[MeasurementVariable] = []
    dimensions = ["point"]
    shape = [len(points)]
    for column in _point_columns(points):
        values = [point.row[column] for point in points if column in point.row]
        if len(values) != len(points):
            continue
        variable = _coordinate_variable(
            column,
            values,
            dimensions=dimensions,
            shape=shape,
        )
        if variable is not None:
            variables.append(variable)
    return variables


def _coordinate_variable(
    column: str,
    values: list[CellValue],
    *,
    dimensions: list[str],
    shape: list[int],
) -> MeasurementVariable | None:
    dtype = _measurement_dtype(values)
    if dtype is None:
        return None
    unit = _compatible_quantity_unit(values)
    metadata: dict[str, Any] = {}
    entity_kind = _entity_kind(values)
    if entity_kind is not None:
        metadata["entity_kind"] = entity_kind
    return MeasurementVariable(
        id=column,
        role="coordinate",
        dtype=dtype,
        unit=unit,
        dims=dimensions,
        shape=shape,
        metadata=metadata,
    )


def _point_columns(points: Sequence[PointRecordLike]) -> list[str]:
    columns: list[str] = []
    for point in points:
        for column in point.row:
            if column not in columns:
                columns.append(column)
    return columns


def _measurement_dtype(values: Sequence[CellValue]) -> MeasurementDType | None:
    if all(isinstance(value, Quantity) for value in values):
        return "float64"
    if all(isinstance(value, bool) for value in values):
        return "bool"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "int64"
    if all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in values
    ):
        return "float64"
    if all(isinstance(value, str) for value in values):
        return "string"
    if all(isinstance(value, EntityRef) for value in values):
        return "string"
    return None


def _entity_kind(values: Sequence[CellValue]) -> str | None:
    entity_values = [value for value in values if isinstance(value, EntityRef)]
    if not entity_values:
        return None
    first_kind = entity_values[0].kind
    if all(value.kind == first_kind for value in entity_values):
        return first_kind
    return None


def _compatible_quantity_unit(values: Sequence[CellValue]) -> str | None:
    quantity_values = [value for value in values if isinstance(value, Quantity)]
    if not quantity_values:
        return None
    first_unit = quantity_values[0].unit
    if all(compatible_units(first_unit, value.unit) for value in quantity_values):
        return first_unit
    return None


def _duplicates(values: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
