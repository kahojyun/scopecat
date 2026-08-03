"""Logical record uses and their config-bound dataset projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from pydantic import JsonValue as WireJsonValue

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping, thaw_json_value
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.point_identity import LogicalPointId, PointDomainLayout
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Scalar,
    String,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.measurements.products import ProductAxisDef, ProductDef
from scopecat.measurements.results import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementVariable,
    MeasurementVariableRole,
)


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class RecordUse:
    """Template-owned durable destination for one logical product use."""

    id: str
    product_use_id: ProductUseId
    role: MeasurementVariableRole = "observable"
    recording_group_id: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "record use id must be non-empty"
            raise ValueError(msg)
        if self.recording_group_id is not None and not self.recording_group_id:
            msg = "recording group id must be non-empty when provided"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(self.metadata, path=f"record use {self.id!r} metadata"),
        )


@dataclass(frozen=True, slots=True)
class ValueRecordUse:
    """Durable destination for one scalar value in the logical graph."""

    id: str
    value_id: ValueId
    source_value_id: str
    value_type: Scalar
    requires_execution: bool = False
    role: MeasurementVariableRole = "observable"
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("value record use id must be non-empty")
        if not self.source_value_id:
            raise ValueError("source value id must be non-empty")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"value record use {self.id!r} metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class RecordAxisPlan:
    id: str
    label: str | None
    kind: str
    size: int | None
    unit: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata, path=f"record axis {self.id!r} metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class RecordPlan:
    id: str
    product_use_id: ProductUseId
    product_id: ProductId
    dtype: MeasurementDType
    role: MeasurementVariableRole = "observable"
    recording_group_id: str | None = None
    unit: str | None = None
    axes: tuple[RecordAxisPlan, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if self.recording_group_id is not None and not self.recording_group_id:
            msg = "recording group id must be non-empty when provided"
            raise ValueError(msg)
        object.__setattr__(self, "axes", tuple(self.axes))
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata, path=f"record plan {self.id!r} metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class ValueRecordPlan:
    """Point-scalar dataset projection for one symbolic program value."""

    id: str
    value_id: ValueId
    source_value_id: str
    dtype: MeasurementDType
    requires_execution: bool = False
    role: MeasurementVariableRole = "observable"
    unit: str | None = None
    recording_group_id: None = field(default=None, init=False)
    axes: tuple[RecordAxisPlan, ...] = field(default=(), init=False)
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("value record plan id must be non-empty")
        if not self.source_value_id:
            raise ValueError("source value id must be non-empty")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"value record plan {self.id!r} metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class ValueRecordCandidate:
    """One point-local scalar value available to dataset projection."""

    logical_point_id: LogicalPointId
    value_id: ValueId
    value: CellValue


type DatasetRecordPlan = RecordPlan | ValueRecordPlan
type BoundRecordUse = RecordUse | ValueRecordUse


class PointRecordLike(Protocol):
    @property
    def row(self) -> Mapping[str, CellValue]: ...


def plan_records(
    products: Sequence[ProductDef],
    product_uses: Sequence[ProductUse],
    record_uses: Sequence[RecordUse],
) -> list[RecordPlan]:
    products_by_id = {product.id: product for product in products}
    uses_by_id = {use.id: use for use in product_uses}
    plans: list[RecordPlan] = []
    for record in record_uses:
        try:
            use = uses_by_id[record.product_use_id]
            product = products_by_id[use.product_id]
        except KeyError as error:
            msg = "record planning requires a closed verified product graph"
            raise ValueError(msg) from error
        plans.append(
            RecordPlan(
                id=record.id,
                product_use_id=use.id,
                product_id=product.id,
                role=record.role,
                recording_group_id=record.recording_group_id,
                unit=product.unit,
                dtype=product.dtype,
                axes=tuple(_plan_axis(axis) for axis in product.axes),
                metadata={**product.metadata, **record.metadata},
            )
        )
    return plans


def plan_value_records(
    record_uses: Sequence[ValueRecordUse],
) -> list[ValueRecordPlan]:
    return [
        ValueRecordPlan(
            id=record.id,
            value_id=record.value_id,
            source_value_id=record.source_value_id,
            dtype=_value_record_dtype(record.value_type),
            requires_execution=record.requires_execution,
            role=record.role,
            unit=_value_record_unit(record.value_type),
            metadata=_value_record_metadata(record),
        )
        for record in record_uses
    ]


def _plan_axis(axis: ProductAxisDef) -> RecordAxisPlan:
    return RecordAxisPlan(
        id=axis.dimension_id,
        label=axis.dimension_label,
        kind=axis.kind,
        size=axis.size,
        unit=axis.unit,
        metadata=axis.metadata,
    )


def validate_record_axes(
    records: Sequence[RecordPlan],
    *,
    phase: ProblemPhase = ProblemPhase.PLANNING,
) -> list[Problem]:
    """Validate compatibility that only becomes concrete after lowering."""

    problems: list[Problem] = []
    axes_by_id: dict[str, tuple[str, RecordAxisPlan]] = {}
    for record in records:
        seen_axis_ids: set[str] = set()
        for axis in record.axes:
            if axis.id in seen_axis_ids:
                continue
            seen_axis_ids.add(axis.id)
            existing = axes_by_id.get(axis.id)
            if existing is None:
                axes_by_id[axis.id] = (record.id, axis)
                continue
            existing_record_id, existing_axis = existing
            if _axes_are_compatible(existing_axis, axis):
                continue
            problems.append(
                problem(
                    "experiment_record_axis_conflict",
                    f"record {record.id!r} axis {axis.label or axis.id!r} conflicts "
                    f"with record {existing_record_id!r} on shared dimension "
                    f"{axis.id!r}; shared axes must have identical labels, kind, "
                    "size, unit, and metadata",
                    phase=phase,
                    location=model_location(
                        "records",
                        record.id,
                        "axes",
                        axis.label or axis.id,
                    ),
                    related_locations=(
                        model_location(
                            "records",
                            existing_record_id,
                            "axes",
                            existing_axis.label or existing_axis.id,
                        ),
                    ),
                )
            )
    return problems


def validate_record_plan(
    records: Sequence[DatasetRecordPlan],
    *,
    coordinate_ids: Sequence[str] = (),
    phase: ProblemPhase = ProblemPhase.PLANNING,
) -> list[Problem]:
    """Validate an independently supplied record plan at a projection boundary."""

    problems: list[Problem] = []
    record_ids = [record.id for record in records]
    duplicate_record_ids = _duplicates(record_ids)
    for record_id in sorted(duplicate_record_ids):
        problems.append(
            problem(
                "experiment_record_duplicate",
                f"experiment record {record_id!r} is duplicated",
                phase=phase,
                location=model_location("records"),
            )
        )
    coordinate_collisions = set(record_ids) & set(coordinate_ids)
    for record_id in sorted(coordinate_collisions):
        problems.append(
            problem(
                "experiment_record_coordinate_collision",
                f"record {record_id!r} conflicts with a point coordinate",
                phase=phase,
                location=model_location("records", record_id),
            )
        )
    dimension_ids = {
        "point",
        *(
            axis.id
            for record in records
            if isinstance(record, RecordPlan)
            for axis in record.axes
        ),
    }
    variable_ids = {*coordinate_ids, *record_ids}
    for variable_id in sorted(dimension_ids & variable_ids):
        problems.append(
            problem(
                "experiment_record_dimension_collision",
                f"measurement variable {variable_id!r} conflicts with a dataset "
                "dimension of the same id",
                phase=phase,
                location=model_location("records", variable_id),
            )
        )
    problems.extend(
        validate_record_axes(
            tuple(record for record in records if isinstance(record, RecordPlan)),
            phase=phase,
        )
    )
    return problems


def expected_dataset_schema(
    *,
    experiment_id: str,
    points: Sequence[PointRecordLike],
    records: Sequence[DatasetRecordPlan],
    dataset_id: str = "raw-measurements",
    point_domain_layout: PointDomainLayout = "product_grid",
    point_domain_axis_sizes: Sequence[tuple[str, int]] = (),
) -> MeasurementDatasetSchema | None:
    if not records:
        return None
    dimensions = [
        MeasurementDimension(id="point", kind="point", size=len(points)),
        *_record_axes(records),
    ]
    point_coordinates = _coordinate_variables(points)
    record_variables = [_record_variable(record) for record in records]
    record_coordinates = [
        variable for variable in record_variables if variable.role == "coordinate"
    ]
    observables = [
        variable for variable in record_variables if variable.role == "observable"
    ]
    coordinates = [*point_coordinates, *record_coordinates]
    return MeasurementDatasetSchema(
        dataset_id=dataset_id,
        dimensions=dimensions,
        variables=[*coordinates, *observables],
        primary_coordinates=[variable.id for variable in coordinates],
        primary_observables=[variable.id for variable in observables],
        metadata={
            "experiment_id": experiment_id,
            "point_domain": {
                "layout": point_domain_layout,
                "axes": [
                    {"id": axis_id, "size": size}
                    for axis_id, size in point_domain_axis_sizes
                ],
            },
        },
    )


def point_coordinate_ids(points: Sequence[PointRecordLike]) -> list[str]:
    return [variable.id for variable in _coordinate_variables(points)]


def _record_axes(records: Sequence[DatasetRecordPlan]) -> list[MeasurementDimension]:
    dimensions: list[MeasurementDimension] = []
    seen: dict[str, RecordAxisPlan] = {}
    for record in records:
        if not isinstance(record, RecordPlan):
            continue
        for axis in record.axes:
            existing = seen.get(axis.id)
            if existing is not None:
                if existing.size is None and axis.size is not None:
                    seen[axis.id] = axis
                    for index, dimension in enumerate(dimensions):
                        if dimension.id == axis.id:
                            dimensions[index] = dimension.model_copy(
                                update={"size": axis.size}
                            )
                            break
                continue
            seen[axis.id] = axis
            dimensions.append(
                MeasurementDimension(
                    id=axis.id,
                    kind=axis.kind,
                    label=axis.label,
                    size=axis.size,
                    metadata=_wire_metadata(axis.metadata),
                )
            )
    return dimensions


def _record_variable(record: DatasetRecordPlan) -> MeasurementVariable:
    if isinstance(record, ValueRecordPlan):
        return MeasurementVariable(
            id=record.id,
            role=record.role,
            dtype=record.dtype,
            unit=record.unit,
            dims=["point"],
            source_value_id=record.source_value_id,
            metadata=_wire_metadata(record.metadata),
        )
    return MeasurementVariable(
        id=record.id,
        role=record.role,
        dtype=record.dtype,
        unit=record.unit,
        dims=["point", *(axis.id for axis in record.axes)],
        source_product_id=record.product_id.qualified_name,
        recording_group_id=record.recording_group_id,
        metadata=_wire_metadata(record.metadata),
    )


def _value_record_dtype(value_type: Scalar) -> MeasurementDType:
    atom = value_type.atom
    if isinstance(atom, Bool):
        return "bool"
    if isinstance(atom, Int):
        return "int64"
    if isinstance(atom, Float | QuantityType):
        return "float64"
    if isinstance(atom, String | Entity):
        return "string"
    raise TypeError("opaque payload values cannot be recorded in a dataset")


def _value_record_unit(value_type: Scalar) -> str | None:
    atom = value_type.atom
    return atom.unit if isinstance(atom, QuantityType) else None


def _value_record_metadata(record: ValueRecordUse) -> Mapping[str, JsonValue]:
    atom = record.value_type.atom
    if not isinstance(atom, Entity) or atom.entity_kind is None:
        return record.metadata
    return {"entity_kind": atom.entity_kind, **record.metadata}


def _axes_are_compatible(left: RecordAxisPlan, right: RecordAxisPlan) -> bool:
    return (
        left.label == right.label
        and left.kind == right.kind
        and (left.size is None or right.size is None or left.size == right.size)
        and left.unit == right.unit
        and left.metadata == right.metadata
    )


def _coordinate_variables(
    points: Sequence[PointRecordLike],
) -> list[MeasurementVariable]:
    variables: list[MeasurementVariable] = []
    dimensions = ["point"]
    for column in _point_columns(points):
        values = [point.row[column] for point in points if column in point.row]
        if len(values) != len(points):
            continue
        variable = _coordinate_variable(
            column,
            values,
            dimensions=dimensions,
        )
        if variable is not None:
            variables.append(variable)
    return variables


def _coordinate_variable(
    column: str,
    values: list[CellValue],
    *,
    dimensions: list[str],
) -> MeasurementVariable | None:
    dtype = _measurement_dtype(values)
    if dtype is None:
        return None
    unit = _compatible_quantity_unit(values)
    metadata: dict[str, WireJsonValue] = {}
    entity_kind = _entity_kind(values)
    if entity_kind is not None:
        metadata["entity_kind"] = entity_kind
    return MeasurementVariable(
        id=column,
        role="coordinate",
        dtype=dtype,
        unit=unit,
        dims=dimensions,
        metadata=metadata,
    )


def _wire_metadata(metadata: Mapping[str, JsonValue]) -> dict[str, WireJsonValue]:
    return cast("dict[str, WireJsonValue]", thaw_json_value(metadata))


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
