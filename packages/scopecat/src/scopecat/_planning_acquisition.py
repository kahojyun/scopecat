from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat._planning_diagnostics import planning_diagnostic
from scopecat.models.parameter import Quantity
from scopecat.relations import CellValue, Row
from scopecat.results import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementVariable,
)
from scopecat.units import compatible_units

type AcquisitionRecordMode = Literal["point", "shot", "trace"]
type ObservationSpecKind = Literal["observable", "artifact"]


class ObservationSpec(BaseModel):
    """Requested measurement output for an acquisition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ObservationSpecKind = "observable"
    unit: str | None = None
    resource: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AcquisitionSpec(BaseModel):
    """Acquisition shape for the experiment kernel."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    shots: int = Field(default=1, gt=0)
    repetitions: int = Field(default=1, gt=0)
    record: AcquisitionRecordMode = "point"
    dimensions: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    observations: list[ObservationSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AcquisitionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    shots: int
    repetitions: int
    record: AcquisitionRecordMode
    dimensions: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    observations: list[ObservationSpec] = Field(default_factory=list)
    estimated_records: int


class ResultIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ObservationSpecKind
    record: AcquisitionRecordMode
    dimensions: list[str] = Field(default_factory=list)
    unit: str | None = None
    resource: str | None = None
    estimated_records: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class PointRecordLike(Protocol):
    @property
    def row(self) -> Row: ...


def estimated_records(acquisition: AcquisitionSpec, point_count: int) -> int:
    if acquisition.record == "shot":
        return point_count * acquisition.shots
    return point_count


def validate_acquisition_plan(acquisition: AcquisitionPlan) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for dimension in sorted(_duplicates(acquisition.dimensions)):
        diagnostics.append(
            planning_diagnostic(
                "error",
                "experiment_acquisition_duplicate_dimension",
                f"acquisition dimension {dimension!r} is duplicated",
                "acquire.dimensions",
            )
        )
    for channel in sorted(_duplicates(acquisition.channels)):
        diagnostics.append(
            planning_diagnostic(
                "error",
                "experiment_acquisition_duplicate_channel",
                f"acquisition channel {channel!r} is duplicated",
                "acquire.channels",
            )
        )
    observation_ids = [observation.id for observation in acquisition.observations]
    for observation_id in sorted(_duplicates(observation_ids)):
        diagnostics.append(
            planning_diagnostic(
                "error",
                "experiment_acquisition_duplicate_observation",
                f"acquisition observation {observation_id!r} is duplicated",
                "acquire.observations",
            )
        )
    return diagnostics


def result_intents(acquisition: AcquisitionPlan) -> list[ResultIntent]:
    return [
        ResultIntent(
            id=observation.id,
            kind=observation.kind,
            record=acquisition.record,
            dimensions=acquisition.dimensions,
            unit=observation.unit,
            resource=observation.resource,
            estimated_records=acquisition.estimated_records,
            metadata=observation.metadata,
        )
        for observation in acquisition.observations
    ]


def expected_dataset_schema(
    *,
    experiment_id: str,
    points: Sequence[PointRecordLike],
    acquisition: AcquisitionPlan,
    result_intents: Sequence[ResultIntent],
) -> MeasurementDatasetSchema | None:
    observable_intents = [
        intent for intent in result_intents if intent.kind == "observable"
    ]
    if not points or not observable_intents:
        return None
    if acquisition.record == "shot":
        dimensions = [
            MeasurementDimension(
                id="shot",
                kind="shot",
                size=acquisition.estimated_records,
                unit="count",
            )
        ]
        dimension_ids = ["shot"]
        coordinates = [
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=dimension_ids,
                shape=[acquisition.estimated_records],
            )
        ]
        observables = [
            MeasurementVariable(
                id=intent.id,
                role="observable",
                dtype="float64",
                unit=intent.unit,
                dims=dimension_ids,
                shape=[acquisition.estimated_records],
                metadata={"record": intent.record, **intent.metadata},
            )
            for intent in observable_intents
        ]
        return MeasurementDatasetSchema(
            dataset_id=f"{experiment_id}.results",
            dataset_role="raw",
            dimensions=dimensions,
            variables=[*coordinates, *observables],
            primary_coordinates=["shot_index"],
            primary_observables=[intent.id for intent in observable_intents],
            metadata={
                "experiment_id": experiment_id,
                "acquisition_kind": acquisition.kind,
                "record": acquisition.record,
            },
        )
    dimensions = [
        MeasurementDimension(id="point", kind="point", size=len(points)),
        *_acquisition_measurement_dimensions(acquisition),
    ]
    dimension_ids = [dimension.id for dimension in dimensions]
    coordinates = _coordinate_variables(points)
    observables = [
        MeasurementVariable(
            id=intent.id,
            role="observable",
            dtype="float64",
            unit=intent.unit,
            dims=dimension_ids,
            shape=_dimension_shape(dimensions),
            metadata={"record": intent.record, **intent.metadata},
        )
        for intent in observable_intents
    ]
    return MeasurementDatasetSchema(
        dataset_id=f"{experiment_id}.results",
        dataset_role="raw",
        dimensions=dimensions,
        variables=[*coordinates, *observables],
        primary_coordinates=[variable.id for variable in coordinates],
        primary_observables=[intent.id for intent in observable_intents],
        metadata={
            "experiment_id": experiment_id,
            "acquisition_kind": acquisition.kind,
            "record": acquisition.record,
        },
    )


def point_coordinate_ids(points: Sequence[PointRecordLike]) -> list[str]:
    return [variable.id for variable in _coordinate_variables(points)]


def _acquisition_measurement_dimensions(
    acquisition: AcquisitionPlan,
) -> list[MeasurementDimension]:
    if acquisition.record == "shot":
        return [MeasurementDimension(id="shot", kind="shot", size=acquisition.shots)]
    if acquisition.record == "trace":
        return [
            MeasurementDimension(id=dimension, kind=dimension)
            for dimension in acquisition.dimensions
        ]
    return []


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
    return MeasurementVariable(
        id=column,
        role="coordinate",
        dtype=dtype,
        unit=unit,
        dims=dimensions,
        shape=shape,
    )


def _point_columns(points: Sequence[PointRecordLike]) -> list[str]:
    columns: list[str] = []
    for point in points:
        for column in point.row:
            if column not in columns:
                columns.append(column)
    return columns


def _measurement_dtype(values: list[CellValue]) -> MeasurementDType | None:
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
    return None


def _compatible_quantity_unit(values: list[CellValue]) -> str | None:
    quantities = [value for value in values if isinstance(value, Quantity)]
    if not quantities:
        return None
    unit = quantities[0].unit
    if not all(compatible_units(unit, quantity.unit) for quantity in quantities):
        return None
    return unit


def _dimension_shape(dimensions: list[MeasurementDimension]) -> list[int]:
    return [dimension.size or 0 for dimension in dimensions]


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
