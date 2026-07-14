"""Independent RecordUse projection over assembled host measurement values."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
)
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.records import (
    RecordPlan,
    RecordUse,
    expected_dataset_schema,
    plan_records,
    point_coordinate_ids,
    validate_record_plan,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem, ProblemCategory, model_location
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    SelectedMeasurementValueAssembly,
    measurement_value_contract_fingerprint,
    require_assembled_measurement_values,
    require_measurement_value_assembly,
)
from scopecat.records.measurement import (
    CoordinateValue,
    MeasurementDatasetSchema,
    MeasurementRecord,
)


@dataclass(frozen=True, slots=True, init=False)
class SelectedMeasurementProjection:
    """Pre-effect selection of template-owned observable record projections."""

    _linked_points: MaterializedLinkedPointSet = field(repr=False)
    _records: tuple[RecordPlan, ...] = field(repr=False)
    required_product_use_ids: tuple[ProductUseId, ...]
    coordinate_ids: tuple[str, ...]
    _schema: MeasurementDatasetSchema | None = field(repr=False)
    linked_contract_fingerprint: str
    contract_fingerprint: str

    def __init__(
        self,
        linked_points: MaterializedLinkedPointSet,
        records: tuple[RecordPlan, ...],
        required_product_use_ids: tuple[ProductUseId, ...],
        coordinate_ids: tuple[str, ...],
        schema: MeasurementDatasetSchema | None,
        linked_contract_fingerprint: str,
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "_linked_points", linked_points)
        object.__setattr__(
            self,
            "_records",
            tuple(deepcopy(record) for record in records),
        )
        object.__setattr__(
            self,
            "required_product_use_ids",
            required_product_use_ids,
        )
        object.__setattr__(self, "coordinate_ids", coordinate_ids)
        object.__setattr__(
            self,
            "_schema",
            None if schema is None else schema.model_copy(deep=True),
        )
        object.__setattr__(
            self,
            "linked_contract_fingerprint",
            linked_contract_fingerprint,
        )
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)

    @property
    def linked_points(self) -> MaterializedLinkedPointSet:
        return self._linked_points

    @property
    def records(self) -> tuple[RecordPlan, ...]:
        return tuple(deepcopy(record) for record in self._records)

    @property
    def schema(self) -> MeasurementDatasetSchema | None:
        return None if self._schema is None else self._schema.model_copy(deep=True)


@dataclass(frozen=True, slots=True, init=False)
class BoundMeasurementProjection:
    """Pre-effect proof that an assembly covers every projected record use."""

    projection: SelectedMeasurementProjection = field(repr=False)
    product_values: SelectedMeasurementValueAssembly = field(repr=False)
    contract_fingerprint: str

    def __init__(
        self,
        projection: SelectedMeasurementProjection,
        product_values: SelectedMeasurementValueAssembly,
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "product_values", product_values)
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


@dataclass(frozen=True, slots=True, init=False)
class ProjectedMeasurementRecords:
    """Canonical complete MeasurementRecord values for one bound projection."""

    selection: BoundMeasurementProjection = field(repr=False)
    run_id: str
    _records: tuple[MeasurementRecord, ...] = field(repr=False)
    _schema: MeasurementDatasetSchema | None = field(repr=False)

    def __init__(
        self,
        selection: BoundMeasurementProjection,
        run_id: str,
        records: tuple[MeasurementRecord, ...],
        schema: MeasurementDatasetSchema | None,
    ) -> None:
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "run_id", run_id)
        selected_records = _snapshot_measurement_records(records)
        object.__setattr__(self, "_records", selected_records)
        selected_schema = None if schema is None else schema.model_copy(deep=True)
        object.__setattr__(
            self,
            "_schema",
            selected_schema,
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

        return self.selection.contract_fingerprint


def select_measurement_projection(
    linked_points: MaterializedLinkedPointSet,
    *,
    record_ids: Sequence[str] | None = None,
) -> SelectedMeasurementProjection:
    """Select observable RecordUse projections without choosing a producer."""

    if not isinstance(
        cast("object", linked_points),
        MaterializedLinkedPoints | MaterializedLinkedPointBatch,
    ):
        msg = "measurement projection requires materialized linked points"
        raise TypeError(msg)
    linked_plan = linked_points.linked_plan
    all_record_uses = tuple(linked_plan.record_uses)
    product_uses = tuple(linked_plan.product_uses)
    product_defs = tuple(linked_plan.product_defs)
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
        if any(
            not isinstance(cast("object", record_id), str) or not record_id
            for record_id in requested_ids
        ):
            msg = "measurement projection record ids must be non-empty strings"
            raise TypeError(msg)
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

    points = linked_points.point_domain.points
    coordinate_ids = tuple(point_coordinate_ids(points))
    record_plans = tuple(
        plan_records(
            product_defs,
            product_uses,
            selected_records,
            point_count=len(points),
        )
    )
    record_problems = validate_record_plan(
        record_plans,
        coordinate_ids=coordinate_ids,
    )
    if record_problems:
        raise CheckFailed(record_problems)
    schema = expected_dataset_schema(
        experiment_id=linked_plan.program.id,
        points=points,
        records=record_plans,
    )
    selected_use_set = {record.product_use_id for record in selected_records}
    required_use_ids = tuple(
        use.id for use in product_uses if use.id in selected_use_set
    )
    linked_fingerprint = measurement_value_contract_fingerprint(linked_points)
    projection_fingerprint = _projection_contract_fingerprint(
        linked_fingerprint,
        record_plans,
        required_use_ids,
        coordinate_ids,
        schema,
    )
    return SelectedMeasurementProjection(
        linked_points,
        record_plans,
        required_use_ids,
        coordinate_ids,
        schema,
        linked_fingerprint,
        projection_fingerprint,
    )


def bind_measurement_projection(
    projection: SelectedMeasurementProjection,
    product_values: SelectedMeasurementValueAssembly,
) -> BoundMeasurementProjection:
    """Prove before effects that selected values cover all record inputs."""

    selected_projection = _require_selected_projection(projection)
    selected_values = require_measurement_value_assembly(product_values)
    problems: list[Problem] = []
    if (
        selected_projection.linked_contract_fingerprint
        != selected_values.linked_contract_fingerprint
    ):
        problems.append(
            _projection_problem(
                "measurement_projection_value_contract_mismatch",
                "measurement projection and value assembly belong to different plans",
                path=("product_values",),
                category=ProblemCategory.CONFLICT,
            )
        )
    selected_use_ids = set(selected_values.product_use_ids)
    for use_id in selected_projection.required_product_use_ids:
        if use_id not in selected_use_ids:
            problems.append(
                _projection_problem(
                    "measurement_projection_value_missing",
                    f"recorded product use {use_id.value!r} has no selected value",
                    path=("product_values", "product_use_ids"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
    if problems:
        raise CheckFailed(problems)
    contract_fingerprint = stable_content_hash(
        {
            "schema": "scopecat.bound_measurement_projection.v1",
            "projection_contract_fingerprint": (
                selected_projection.contract_fingerprint
            ),
            "value_contract_fingerprint": selected_values.contract_fingerprint,
        }
    )
    return BoundMeasurementProjection(
        selected_projection,
        selected_values,
        contract_fingerprint,
    )


def project_measurement_records(
    selection: BoundMeasurementProjection,
    product_values: ClosedMeasurementProductValues,
    *,
    run_id: str,
) -> ProjectedMeasurementRecords:
    """Project complete canonical point records without changing product values."""

    bound = _require_bound_projection(selection)
    if not run_id:
        msg = "measurement projection run_id must be non-empty"
        raise ValueError(msg)
    values = require_assembled_measurement_values(product_values)
    if (
        values.selection.contract_fingerprint
        != bound.product_values.contract_fingerprint
    ):
        msg = "assembled measurement values do not belong to this projection"
        raise ValueError(msg)
    projection = bound.projection
    record_plans = projection.records
    if not record_plans:
        records: tuple[MeasurementRecord, ...] = ()
    else:
        records = tuple(
            MeasurementRecord(
                run_id=run_id,
                point_index=point.logical_ordinal,
                coordinates=_point_coordinates(point.row, projection.coordinate_ids),
                observables={
                    record.id: values.value_for_output(
                        point.logical_id,
                        record.product_use_id,
                    ).value
                    for record in record_plans
                },
                metadata={"logical_point_id": point.logical_id.value},
            )
            for point in projection.linked_points.point_domain.points
        )
    return ProjectedMeasurementRecords(
        bound,
        run_id,
        records,
        projection.schema,
    )


def require_projected_measurement_records(
    projected: ProjectedMeasurementRecords,
) -> ProjectedMeasurementRecords:
    """Require the projected stage produced by record projection."""

    if not isinstance(cast("object", projected), ProjectedMeasurementRecords):
        msg = "measurement recording requires ProjectedMeasurementRecords"
        raise TypeError(msg)
    return projected


def _require_selected_projection(
    projection: SelectedMeasurementProjection,
) -> SelectedMeasurementProjection:
    if not isinstance(cast("object", projection), SelectedMeasurementProjection):
        msg = "measurement projection requires SelectedMeasurementProjection"
        raise TypeError(msg)
    return projection


def _require_bound_projection(
    selection: BoundMeasurementProjection,
) -> BoundMeasurementProjection:
    if not isinstance(cast("object", selection), BoundMeasurementProjection):
        msg = "measurement records require BoundMeasurementProjection"
        raise TypeError(msg)
    return selection


def _projection_contract_fingerprint(
    linked_fingerprint: str,
    records: Sequence[RecordPlan],
    required_product_use_ids: Sequence[ProductUseId],
    coordinate_ids: Sequence[str],
    schema: MeasurementDatasetSchema | None,
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurements.projection_contract.v1",
                "linked_contract_fingerprint": linked_fingerprint,
                "records": tuple(records),
                "required_product_use_ids": tuple(
                    use_id.value for use_id in required_product_use_ids
                ),
                "coordinate_ids": tuple(coordinate_ids),
                "dataset_schema": schema,
            }
        )
    )


def _snapshot_measurement_records(
    records: Sequence[MeasurementRecord],
) -> tuple[MeasurementRecord, ...]:
    if any(
        not isinstance(cast("object", record), MeasurementRecord) for record in records
    ):
        msg = "projected values require MeasurementRecord instances"
        raise TypeError(msg)
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


__all__ = [
    "BoundMeasurementProjection",
    "ProjectedMeasurementRecords",
    "SelectedMeasurementProjection",
    "bind_measurement_projection",
    "project_measurement_records",
    "require_projected_measurement_records",
    "select_measurement_projection",
]
