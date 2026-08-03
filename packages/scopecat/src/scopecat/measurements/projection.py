"""Independent RecordUse projection over assembled host measurement values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue as WireJsonValue

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import Problem, ProblemPhase, model_location, problem
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.measurements.points import RunPoint
from scopecat.measurements.products import ProductDef
from scopecat.measurements.records import (
    BoundRecordUse,
    DatasetRecordPlan,
    RecordPlan,
    RecordUse,
    ValueRecordCandidate,
    ValueRecordPlan,
    ValueRecordUse,
    expected_dataset_schema,
    plan_records,
    plan_value_records,
    validate_record_plan,
)
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    MeasurementValueCatalog,
)
from scopecat.records.measurement import (
    InstrumentAcquisitionEvidence,
    MeasurementDatasetSchema,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementValue,
    MeasurementVariableRole,
)


@dataclass(frozen=True, slots=True, init=False)
class MeasurementProjection:
    """Closed pre-effect plan for durable measurement variables."""

    catalog: MeasurementValueCatalog = field(repr=False)
    _records: tuple[DatasetRecordPlan, ...] = field(repr=False)
    _static_value_candidates: tuple[ValueRecordCandidate, ...] = field(
        repr=False,
        compare=False,
    )
    contract_fingerprint: str

    def __init__(
        self,
        catalog: MeasurementValueCatalog,
        records: tuple[DatasetRecordPlan, ...],
        *,
        static_value_candidates: Sequence[ValueRecordCandidate] = (),
    ) -> None:
        object.__setattr__(self, "catalog", catalog)
        object.__setattr__(self, "_records", records)
        object.__setattr__(
            self,
            "_static_value_candidates",
            tuple(static_value_candidates),
        )
        object.__setattr__(
            self,
            "contract_fingerprint",
            _projection_contract_fingerprint(
                catalog.contract_fingerprint,
                records,
                catalog.point_contract.coordinate_ids,
            ),
        )

    @property
    def records(self) -> tuple[DatasetRecordPlan, ...]:
        return self._records

    @property
    def runtime_value_ids(self) -> tuple[ValueId, ...]:
        return tuple(
            dict.fromkeys(
                record.value_id
                for record in self.records
                if isinstance(record, ValueRecordPlan) and record.requires_execution
            )
        )

    @property
    def static_value_candidates(self) -> tuple[ValueRecordCandidate, ...]:
        return self._static_value_candidates

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self.catalog.point_contract.coordinate_ids

    def schema_for(
        self,
        points: Sequence[RunPoint],
    ) -> MeasurementDatasetSchema | None:
        selected = tuple(points)
        if not self.records:
            return None
        return expected_dataset_schema(
            experiment_id=self.catalog.point_contract.experiment_id,
            point_count=len(selected),
            records=self.records,
            point_coordinate_columns=self.catalog.point_contract.coordinate_columns,
            point_domain_layout=self.catalog.point_contract.domain_layout,
            point_domain_axis_sizes=self.catalog.point_contract.domain_axis_sizes,
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
    record_uses: Sequence[BoundRecordUse],
    *,
    static_value_candidates: Sequence[ValueRecordCandidate] = (),
) -> MeasurementProjection:
    """Close every record projection against one value catalog."""

    selected_records = tuple(record_uses)
    product_records = tuple(
        record for record in selected_records if isinstance(record, RecordUse)
    )
    value_records = tuple(
        record for record in selected_records if isinstance(record, ValueRecordUse)
    )
    product_uses = catalog.product_uses
    product_defs = catalog.product_defs
    use_by_id = {use.id: use for use in product_uses}
    product_by_id = {product.id: product for product in product_defs}
    problems: list[Problem] = []

    for index, record in enumerate(product_records):
        if not _record_product_exists(record, use_by_id, product_by_id):
            problems.append(
                _projection_problem(
                    "measurement_projection_product_missing",
                    f"record {record.id!r} does not resolve to a logical product",
                    path=("records", index, "product_use_id"),
                )
            )
    if problems:
        raise CheckFailed(problems)

    coordinate_ids = catalog.point_contract.coordinate_ids
    product_record_iterator = iter(
        plan_records(
            product_defs,
            product_uses,
            product_records,
        )
    )
    value_record_iterator = iter(plan_value_records(value_records))
    record_plans: tuple[DatasetRecordPlan, ...] = tuple(
        next(product_record_iterator)
        if isinstance(record, RecordUse)
        else next(value_record_iterator)
        for record in selected_records
    )
    record_problems = validate_record_plan(
        record_plans,
        coordinate_ids=coordinate_ids,
    )
    if record_problems:
        raise CheckFailed(record_problems)
    return MeasurementProjection(
        catalog,
        record_plans,
        static_value_candidates=static_value_candidates,
    )


def project_measurement_records(
    projection: MeasurementProjection,
    product_values: ClosedMeasurementProductValues,
    *,
    run_id: str,
    points: Sequence[RunPoint],
    value_candidates: Sequence[ValueRecordCandidate] = (),
) -> ProjectedMeasurementDataset:
    """Project one closed admitted point range without changing product values."""

    if not run_id:
        msg = "measurement projection run_id must be non-empty"
        raise ValueError(msg)
    values = product_values
    if values.catalog.contract_fingerprint != projection.catalog.contract_fingerprint:
        msg = "assembled measurement values do not belong to this projection"
        raise ValueError(msg)
    record_plans = projection.records
    points = tuple(points)
    value_candidates_by_key = {
        (candidate.logical_point_id, candidate.value_id): candidate.value
        for candidate in (
            *projection.static_value_candidates,
            *value_candidates,
        )
    }
    if not record_plans:
        records: tuple[MeasurementRecord, ...] = ()
    else:
        records = tuple(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id=point.logical_id.value,
                point_index=point.logical_ordinal,
                coordinates={
                    **_point_coordinates(point.row, projection.coordinate_ids),
                    **_projected_values(
                        record_plans,
                        role="coordinate",
                        product_values=values,
                        value_candidates=value_candidates_by_key,
                        point=point,
                    ),
                },
                observables=_projected_values(
                    record_plans,
                    role="observable",
                    product_values=values,
                    value_candidates=value_candidates_by_key,
                    point=point,
                ),
                acquisition_evidence=_projected_acquisition_evidence(
                    record_plans,
                    product_values=values,
                    point=point,
                ),
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
    records: Sequence[DatasetRecordPlan],
    coordinate_ids: Sequence[str],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurements.projection_contract.v6",
                "catalog_fingerprint": catalog_fingerprint,
                "records": tuple(_record_contract(record) for record in records),
                "coordinate_ids": tuple(coordinate_ids),
            }
        )
    )


def _record_contract(record: DatasetRecordPlan) -> object:
    if isinstance(record, RecordPlan):
        return record
    return {
        "kind": "value",
        "id": record.id,
        "source_value_id": record.source_value_id,
        "dtype": record.dtype,
        "requires_execution": record.requires_execution,
        "role": record.role,
        "unit": record.unit,
        "metadata": record.metadata,
    }


def _projected_values(
    records: Sequence[DatasetRecordPlan],
    *,
    role: MeasurementVariableRole,
    product_values: ClosedMeasurementProductValues,
    value_candidates: Mapping[tuple[LogicalPointId, ValueId], CellValue],
    point: RunPoint,
) -> dict[str, MeasurementValue]:
    projected: dict[str, MeasurementValue] = {}
    for record in records:
        if record.role != role:
            continue
        if isinstance(record, RecordPlan):
            projected[record.id] = product_values.value_for_output(
                point.logical_id,
                record.product_use_id,
            ).value
            continue
        try:
            value = value_candidates[(point.logical_id, record.value_id)]
        except KeyError as error:
            raise ValueError(
                f"recorded value {record.id!r} is unavailable for point "
                f"{point.logical_ordinal}"
            ) from error
        projected[record.id] = _measurement_coordinate(value)
    return projected


def _projected_acquisition_evidence(
    records: Sequence[DatasetRecordPlan],
    *,
    product_values: ClosedMeasurementProductValues,
    point: RunPoint,
) -> dict[str, InstrumentAcquisitionEvidence]:
    acquisition_evidence: dict[str, InstrumentAcquisitionEvidence] = {}
    for record in records:
        if not isinstance(record, RecordPlan):
            continue
        evidence = product_values.value_for_output(
            point.logical_id,
            record.product_use_id,
        ).evidence
        if evidence is not None:
            acquisition_evidence[record.id] = evidence
    return acquisition_evidence


def _snapshot_measurement_records(
    records: Sequence[MeasurementRecord],
) -> tuple[MeasurementRecord, ...]:
    return tuple(deepcopy(record) for record in records)


def _record_product_exists(
    record: RecordUse,
    use_by_id: Mapping[ProductUseId, ProductUse],
    product_by_id: Mapping[ProductId, ProductDef],
) -> bool:
    use = use_by_id.get(record.product_use_id)
    if use is None:
        return False
    return use.product_id in product_by_id


def _point_coordinates(
    row: Mapping[str, CellValue],
    coordinate_ids: Sequence[str],
) -> dict[str, MeasurementValue]:
    return {
        coordinate_id: _measurement_coordinate(row[coordinate_id])
        for coordinate_id in coordinate_ids
    }


def _measurement_coordinate(value: CellValue) -> MeasurementScalar:
    if isinstance(value, Quantity):
        return MeasurementScalar.create(
            dtype="float64",
            unit=value.unit,
            value=value.value,
        )
    if isinstance(value, EntityRef):
        entity: dict[str, WireJsonValue] = {}
        if value.kind is not None:
            entity["kind"] = value.kind
        if value.metadata:
            entity["metadata"] = cast(
                "WireJsonValue",
                thaw_json_value(value.metadata),
            )
        return MeasurementScalar.create(
            dtype="string",
            value=value.id,
            metadata={"entity": entity},
        )
    if isinstance(value, bool):
        return MeasurementScalar.create(dtype="bool", value=value)
    if isinstance(value, int):
        return MeasurementScalar.create(dtype="int64", value=value)
    if isinstance(value, float):
        return MeasurementScalar.create(dtype="float64", value=value)
    if isinstance(value, str):
        return MeasurementScalar.create(dtype="string", value=value)
    raise TypeError(f"unsupported persisted point coordinate: {type(value).__name__}")


def _projection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PLANNING,
        location=model_location("measurement_projection", *path),
    )
