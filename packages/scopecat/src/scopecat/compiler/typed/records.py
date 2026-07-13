"""Logical record uses and their config-bound dataset projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.model import (
    CellValue,
    Row,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.units import compatible_units, is_supported_unit
from scopecat.measurements.results import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementVariable,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


class RecordUse(BaseModel):
    """Template-owned durable destination for one logical product use."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str = Field(min_length=1)
    product_use_id: ProductUseId
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordAxisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    product_use_id: ProductUseId
    product_id: ProductId
    kind: str
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
    products: Sequence[ProductDef],
    product_uses: Sequence[ProductUse],
    record_uses: Sequence[RecordUse],
    *,
    point_count: int,
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
                kind=product.kind,
                unit=product.unit,
                dtype=product.dtype,
                axes=[_plan_axis(axis) for axis in product.axes],
                dims=["point", *(axis.id for axis in product.axes)],
                shape=[point_count, *(axis.size for axis in product.axes)],
                metadata={**product.metadata, **record.metadata},
            )
        )
    return plans


def validate_product_graph(
    products: Sequence[ProductDef],
    producers: Sequence[InstrumentProductProducer],
    product_uses: Sequence[ProductUse],
    record_uses: Sequence[RecordUse],
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> tuple[Problem, ...]:
    """Check declaration/use/record closure without choosing a target."""

    problems: list[Problem] = []
    product_counts = Counter(product.id for product in products)
    products_by_id = {product.id: product for product in products}
    for product_id, count in product_counts.items():
        if count < 2:
            continue
        problems.append(
            compiler_problem(
                "product_definition_duplicate",
                f"logical product {product_id.qualified_name!r} is defined "
                "more than once",
                model_location("product_defs", product_id.qualified_name),
                phase=phase,
                category=ProblemCategory.CONFLICT,
            )
        )

    producer_counts = Counter(producer.id for producer in producers)
    for producer_id, count in producer_counts.items():
        if count < 2:
            continue
        problems.append(
            compiler_problem(
                "product_producer_duplicate",
                f"product producer {producer_id.qualified_name!r} is declared "
                "more than once",
                model_location(
                    "instrument_product_producers",
                    producer_id.qualified_name,
                ),
                phase=phase,
                category=ProblemCategory.CONFLICT,
            )
        )
    for producer in producers:
        if producer.product_id in products_by_id:
            continue
        problems.append(
            compiler_problem(
                "product_producer_definition_missing",
                f"product producer {producer.id.qualified_name!r} references "
                f"unknown product {producer.product_id.qualified_name!r}",
                model_location(
                    "instrument_product_producers",
                    producer.id.qualified_name,
                    "product_id",
                ),
                phase=phase,
                category=ProblemCategory.NOT_FOUND,
            )
        )

    use_counts = Counter(use.id for use in product_uses)
    uses_by_id = {use.id: use for use in product_uses}
    for use_id, count in use_counts.items():
        if count < 2:
            continue
        problems.append(
            compiler_problem(
                "product_use_identity_duplicate",
                f"product use {use_id.value!r} occurs more than once",
                model_location("product_uses", use_id.value),
                phase=phase,
                category=ProblemCategory.CONFLICT,
            )
        )
    for use in product_uses:
        if use.product_id in products_by_id:
            continue
        problems.append(
            compiler_problem(
                "product_use_definition_missing",
                f"product use {use.id.value!r} references unknown product "
                f"{use.product_id.qualified_name!r}",
                model_location("product_uses", use.id.value, "product_id"),
                phase=phase,
                category=ProblemCategory.NOT_FOUND,
            )
        )

    for record in record_uses:
        if record.product_use_id in uses_by_id:
            continue
        problems.append(
            compiler_problem(
                "record_product_use_missing",
                f"record {record.id!r} references unknown product use "
                f"{record.product_use_id.value!r}",
                model_location("record_uses", record.id, "product_use_id"),
                phase=phase,
                category=ProblemCategory.NOT_FOUND,
            )
        )
    return tuple(problems)


def _plan_axis(axis: ProductAxisDef) -> RecordAxisPlan:
    return RecordAxisPlan(
        id=axis.id,
        kind=axis.kind,
        size=axis.size,
        unit=axis.unit,
        metadata=axis.metadata,
    )


def validate_product_defs(
    products: Sequence[ProductDef],
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> tuple[Problem, ...]:
    """Validate intrinsic product schema independently of demand or recording."""

    problems: list[Problem] = []
    for product in products:
        product_name = product.id.qualified_name
        if product.unit is not None and not is_supported_unit(product.unit):
            problems.append(
                compiler_problem(
                    "product_unit_unsupported",
                    f"product {product_name!r} uses unsupported unit {product.unit!r}",
                    model_location("product_defs", product_name, "unit"),
                    phase=phase,
                )
            )
        axis_ids = [axis.id for axis in product.axes]
        for axis_id in sorted(_duplicates(axis_ids)):
            problems.append(
                compiler_problem(
                    "product_axis_duplicate",
                    f"product {product_name!r} axis {axis_id!r} is duplicated",
                    model_location("product_defs", product_name, "axes"),
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                )
            )
        for axis in product.axes:
            location = model_location(
                "product_defs",
                product_name,
                "axes",
                axis.id,
            )
            if axis.id == "point":
                problems.append(
                    compiler_problem(
                        "product_axis_reserved",
                        "product axis 'point' conflicts with the point dimension",
                        location,
                        phase=phase,
                    )
                )
            if axis.unit is not None and not is_supported_unit(axis.unit):
                problems.append(
                    compiler_problem(
                        "product_axis_unit_unsupported",
                        f"product {product_name!r} axis {axis.id!r} uses "
                        f"unsupported unit {axis.unit!r}",
                        model_location(location.root, *location.path, "unit"),
                        phase=phase,
                    )
                )
    return tuple(problems)


def validate_record_plan(
    records: Sequence[RecordPlan],
    *,
    coordinate_ids: Sequence[str] = (),
    phase: ProblemPhase = ProblemPhase.PLANNING,
) -> list[Problem]:
    problems: list[Problem] = []
    record_ids = [record.id for record in records]
    duplicate_record_ids = _duplicates(record_ids)
    for record_id in sorted(duplicate_record_ids):
        problems.append(
            compiler_problem(
                "experiment_record_duplicate",
                f"experiment record {record_id!r} is duplicated",
                model_location("records"),
                phase=phase,
                category=ProblemCategory.CONFLICT,
            )
        )
    coordinate_collisions = set(record_ids) & set(coordinate_ids)
    for record_id in sorted(coordinate_collisions):
        problems.append(
            compiler_problem(
                "experiment_record_coordinate_collision",
                f"record {record_id!r} conflicts with a point coordinate",
                model_location("records", record_id),
                phase=phase,
                category=ProblemCategory.CONFLICT,
            )
        )
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
                compiler_problem(
                    "experiment_record_axis_conflict",
                    f"record {record.id!r} axis {axis.id!r} conflicts with "
                    f"record {existing_record_id!r}; shared axes must have "
                    "identical kind, size, unit, and metadata",
                    model_location("records", record.id, "axes", axis.id),
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                    related_locations=(
                        model_location(
                            "records",
                            existing_record_id,
                            "axes",
                            axis.id,
                        ),
                    ),
                )
            )
    return problems


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


def _axes_are_compatible(left: RecordAxisPlan, right: RecordAxisPlan) -> bool:
    return (
        left.kind == right.kind
        and left.size == right.size
        and left.unit == right.unit
        and left.metadata == right.metadata
    )


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


__all__ = [
    "PointRecordLike",
    "RecordAxisPlan",
    "RecordPlan",
    "RecordUse",
    "expected_dataset_schema",
    "plan_records",
    "point_coordinate_ids",
    "validate_product_defs",
    "validate_product_graph",
    "validate_record_plan",
]
