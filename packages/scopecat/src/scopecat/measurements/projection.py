"""Independent RecordUse projection over assembled host measurement values."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.records import (
    RecordPlan,
    RecordUse,
    expected_dataset_schema,
    plan_records,
    validate_record_plan,
)
from scopecat.execution.points import RunPoint
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem, ProblemCategory, model_location
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    MeasurementValueCatalog,
    MeasurementValueSelection,
    measurement_value_contract_fingerprint,
    select_measurement_values,
)
from scopecat.records.measurement import (
    CoordinateValue,
    MeasurementDatasetSchema,
    MeasurementRecord,
)


@dataclass(frozen=True, slots=True, init=False)
class MeasurementProjection:
    """Closed pre-effect plan for observable measurement records."""

    catalog: MeasurementValueCatalog = field(repr=False)
    _records: tuple[RecordPlan, ...] = field(repr=False)
    required_product_use_ids: tuple[ProductUseId, ...]
    coordinate_ids: tuple[str, ...]
    product_values: MeasurementValueSelection = field(repr=False)
    catalog_fingerprint: str
    contract_fingerprint: str

    def __init__(
        self,
        catalog: MeasurementValueCatalog,
        records: tuple[RecordPlan, ...],
        required_product_use_ids: tuple[ProductUseId, ...],
        coordinate_ids: tuple[str, ...],
        product_values: MeasurementValueSelection,
    ) -> None:
        object.__setattr__(self, "catalog", catalog)
        object.__setattr__(self, "_records", records)
        object.__setattr__(
            self,
            "required_product_use_ids",
            required_product_use_ids,
        )
        object.__setattr__(self, "coordinate_ids", coordinate_ids)
        object.__setattr__(self, "product_values", product_values)
        catalog_fingerprint = measurement_value_contract_fingerprint(catalog)
        object.__setattr__(self, "catalog_fingerprint", catalog_fingerprint)
        object.__setattr__(
            self,
            "contract_fingerprint",
            stable_content_hash(
                {
                    "schema": "scopecat.measurement_projection.v1",
                    "projection_contract_fingerprint": _projection_contract_fingerprint(
                        catalog_fingerprint,
                        records,
                        required_product_use_ids,
                        coordinate_ids,
                    ),
                    "value_contract_fingerprint": product_values.contract_fingerprint,
                }
            ),
        )

    @property
    def records(self) -> tuple[RecordPlan, ...]:
        return self._records

    def schema_for(
        self,
        points: Sequence[RunPoint],
    ) -> MeasurementDatasetSchema | None:
        selected = tuple(points)
        if not self.records:
            return None
        return expected_dataset_schema(
            experiment_id=self.catalog.point_contract.experiment_id,
            points=selected,
            records=tuple(
                replace(record, shape=(len(selected), *record.shape[1:]))
                for record in self.records
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class ProjectedMeasurementDataset:
    """Canonical measurement records for one projection and point range."""

    projection: MeasurementProjection = field(repr=False)
    run_id: str
    _records: tuple[MeasurementRecord, ...] = field(repr=False)
    _schema: MeasurementDatasetSchema | None = field(repr=False)

    def __init__(
        self,
        projection: MeasurementProjection,
        run_id: str,
        records: tuple[MeasurementRecord, ...],
        *,
        points: Sequence[RunPoint],
    ) -> None:
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "run_id", run_id)
        selected_records = _snapshot_measurement_records(records)
        object.__setattr__(self, "_records", selected_records)
        object.__setattr__(
            self,
            "_schema",
            projection.schema_for(points),
        )

    @property
    def records(self) -> tuple[MeasurementRecord, ...]:
        return tuple(record.model_copy(deep=True) for record in self._records)

    @property
    def schema(self) -> MeasurementDatasetSchema | None:
        return None if self._schema is None else self._schema.model_copy(deep=True)

    @property
    def recording_contract_fingerprint(self) -> str:
        """Return the pre-value contract shared by every record chunk."""

        return self.projection.contract_fingerprint


def select_measurement_projection(
    catalog: MeasurementValueCatalog,
    record_uses: Sequence[RecordUse],
    *,
    record_ids: Sequence[str] | None = None,
) -> MeasurementProjection:
    """Close observable record projections against selected product values."""

    all_record_uses = tuple(record_uses)
    product_uses = catalog.product_uses
    product_values = select_measurement_values(
        catalog,
        required_product_use_ids=tuple(use.id for use in product_uses),
    )
    product_defs = catalog.product_defs
    use_by_id = {use.id: use for use in product_uses}
    product_by_id = {product.id: product for product in product_defs}
    record_by_id = {record.id: record for record in all_record_uses}
    problems: list[Problem] = []

    if record_ids is None:
        selected_ids = tuple(
            record.id
            for record in all_record_uses
            if _record_product_kind(record, use_by_id, product_by_id) == "observable"
        )
    else:
        requested_ids = tuple(record_ids)
        if any(not record_id for record_id in requested_ids):
            msg = "measurement projection record ids must be non-empty strings"
            raise ValueError(msg)
        for record_id, count in Counter(requested_ids).items():
            if count > 1:
                problems.append(
                    _projection_problem(
                        "measurement_projection_record_duplicate",
                        f"record projection {record_id!r} is selected more than once",
                        path=("record_ids",),
                        category=ProblemCategory.CONFLICT,
                    )
                )
        for index, record_id in enumerate(requested_ids):
            if record_id not in record_by_id:
                problems.append(
                    _projection_problem(
                        "measurement_projection_record_unknown",
                        f"record projection {record_id!r} does not exist",
                        path=("record_ids", index),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
        requested_set = set(requested_ids)
        selected_ids = tuple(
            record.id for record in all_record_uses if record.id in requested_set
        )

    selected_records = tuple(record_by_id[record_id] for record_id in selected_ids)
    for index, record in enumerate(selected_records):
        kind = _record_product_kind(record, use_by_id, product_by_id)
        if kind is None:
            problems.append(
                _projection_problem(
                    "measurement_projection_product_missing",
                    f"record {record.id!r} does not resolve to a logical product",
                    path=("records", index, "product_use_id"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        elif kind != "observable":
            problems.append(
                _projection_problem(
                    "measurement_projection_product_kind_unsupported",
                    f"record {record.id!r} requires unsupported {kind!r} carrier",
                    path=("records", index),
                )
            )
    if problems:
        raise CheckFailed(problems)

    coordinate_ids = catalog.point_contract.coordinate_ids
    record_plans = tuple(
        plan_records(
            product_defs,
            product_uses,
            selected_records,
            point_count=0,
        )
    )
    record_problems = validate_record_plan(
        record_plans,
        coordinate_ids=coordinate_ids,
    )
    if record_problems:
        raise CheckFailed(record_problems)
    selected_use_set = {record.product_use_id for record in selected_records}
    required_use_ids = tuple(
        use.id for use in product_uses if use.id in selected_use_set
    )
    return MeasurementProjection(
        catalog,
        record_plans,
        required_use_ids,
        coordinate_ids,
        product_values,
    )


def project_measurement_records(
    projection: MeasurementProjection,
    product_values: ClosedMeasurementProductValues,
    *,
    run_id: str,
    points: Sequence[RunPoint],
) -> ProjectedMeasurementDataset:
    """Project one closed admitted point range without changing product values."""

    if not run_id:
        msg = "measurement projection run_id must be non-empty"
        raise ValueError(msg)
    values = product_values
    if (
        values.selection.contract_fingerprint
        != projection.product_values.contract_fingerprint
    ):
        msg = "assembled measurement values do not belong to this projection"
        raise ValueError(msg)
    record_plans = projection.records
    points = tuple(points)
    if not record_plans:
        records: tuple[MeasurementRecord, ...] = ()
    else:
        records = tuple(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id=point.logical_id.value,
                point_index=point.logical_ordinal,
                coordinates=_point_coordinates(point.row, projection.coordinate_ids),
                observables={
                    record.id: values.value_for_output(
                        point.logical_id,
                        record.product_use_id,
                    ).value
                    for record in record_plans
                },
            )
            for point in points
        )
    return ProjectedMeasurementDataset(
        projection,
        run_id,
        records,
        points=points,
    )


def _projection_contract_fingerprint(
    catalog_fingerprint: str,
    records: Sequence[RecordPlan],
    required_product_use_ids: Sequence[ProductUseId],
    coordinate_ids: Sequence[str],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurements.projection_contract.v1",
                "catalog_fingerprint": catalog_fingerprint,
                "records": tuple(
                    replace(record, shape=(0, *record.shape[1:])) for record in records
                ),
                "required_product_use_ids": tuple(
                    use_id.value for use_id in required_product_use_ids
                ),
                "coordinate_ids": tuple(coordinate_ids),
            }
        )
    )


def _snapshot_measurement_records(
    records: Sequence[MeasurementRecord],
) -> tuple[MeasurementRecord, ...]:
    return tuple(deepcopy(record) for record in records)


def _record_product_kind(
    record: RecordUse,
    use_by_id: Mapping[ProductUseId, ProductUse],
    product_by_id: Mapping[ProductId, ProductDef],
) -> str | None:
    use = use_by_id.get(record.product_use_id)
    if use is None:
        return None
    product = product_by_id.get(use.product_id)
    return None if product is None else product.kind


def _point_coordinates(
    row: Mapping[str, object],
    coordinate_ids: Sequence[str],
) -> dict[str, CoordinateValue]:
    coordinates: dict[str, CoordinateValue] = {}
    for coordinate_id in coordinate_ids:
        value = row[coordinate_id]
        coordinates[coordinate_id] = cast("CoordinateValue", deepcopy(value))
    return coordinates


def _projection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_projection", *path),
        category=category,
    )
