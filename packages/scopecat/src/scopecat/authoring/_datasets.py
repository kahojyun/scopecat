from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.authoring._templates import ExperimentAuthoringContext
from scopecat.authoring.expressions import ExperimentVariable
from scopecat.results import (
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementVariable,
    MeasurementVariableRole,
)


@dataclass(frozen=True)
class DatasetColumn:
    id: str
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    label: str | None = None


@dataclass(frozen=True)
class PointDatasetIntent:
    coordinates: tuple[DatasetColumn, ...]
    observables: tuple[DatasetColumn, ...]
    dataset_id: str = "raw-measurements"
    dataset_role: MeasurementDatasetRole = "raw"
    dimension_id: str = "point"
    dimension_kind: str = "point"
    dimension_label: str = "Point"

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        variables: Mapping[str, ExperimentVariable],
    ) -> MeasurementDatasetSchema:
        point_count = _point_count_for_coordinates(ctx, self.coordinates, variables)
        return MeasurementDatasetSchema(
            dataset_id=self.dataset_id,
            dataset_role=self.dataset_role,
            dimensions=[
                MeasurementDimension(
                    id=self.dimension_id,
                    kind=self.dimension_kind,
                    label=self.dimension_label,
                    size=point_count,
                )
            ],
            variables=[
                *[
                    _measurement_variable(
                        column,
                        role="coordinate",
                        dims=[self.dimension_id],
                        shape=[point_count],
                        unit=column.unit or _variable_unit(ctx, column.id, variables),
                    )
                    for column in self.coordinates
                ],
                *[
                    _measurement_variable(
                        column,
                        role="observable",
                        dims=[self.dimension_id],
                        shape=[point_count],
                        unit=column.unit,
                    )
                    for column in self.observables
                ],
            ],
            primary_coordinates=[column.id for column in self.coordinates],
            primary_observables=[column.id for column in self.observables],
        )


@dataclass(frozen=True)
class ShotDatasetIntent:
    observables: tuple[DatasetColumn, ...]
    count_parameter_id: str
    dataset_id: str = "raw-measurements"
    dataset_role: MeasurementDatasetRole = "raw"
    dimension_id: str = "shot"
    coordinate_id: str = "shot_index"

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        variables: Mapping[str, ExperimentVariable],
    ) -> MeasurementDatasetSchema:
        del variables
        count = ctx.require_parameter(self.count_parameter_id)
        if count.unit != "count":
            ctx.raise_diagnostic(
                "recipe_shot_count_unit_invalid",
                f"{self.count_parameter_id} must use count units",
                self.count_parameter_id,
            )
        shot_count = int(count.value)
        return MeasurementDatasetSchema(
            dataset_id=self.dataset_id,
            dataset_role=self.dataset_role,
            dimensions=[
                MeasurementDimension(
                    id=self.dimension_id,
                    kind="shot",
                    label="Shot",
                    size=shot_count,
                    unit="count",
                )
            ],
            variables=[
                MeasurementVariable(
                    id=self.coordinate_id,
                    role="coordinate",
                    dtype="int64",
                    unit="count",
                    dims=[self.dimension_id],
                    shape=[shot_count],
                ),
                *[
                    _measurement_variable(
                        column,
                        role="observable",
                        dims=[self.dimension_id],
                        shape=[shot_count],
                        unit=column.unit,
                    )
                    for column in self.observables
                ],
            ],
            primary_coordinates=[self.coordinate_id],
            primary_observables=[column.id for column in self.observables],
        )


DatasetIntent = PointDatasetIntent | ShotDatasetIntent


def coordinate(
    id: str,  # noqa: A002
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    label: str | None = None,
) -> DatasetColumn:
    return DatasetColumn(id=id, unit=unit, dtype=dtype, label=label)


def observable(
    id: str,  # noqa: A002
    *,
    unit: str | None = "ratio",
    dtype: MeasurementDType = "float64",
    label: str | None = None,
) -> DatasetColumn:
    return DatasetColumn(id=id, unit=unit, dtype=dtype, label=label)


def point_dataset(
    *,
    coordinates: Sequence[DatasetColumn | str],
    observables: Sequence[DatasetColumn | str],
    dataset_id: str = "raw-measurements",
    dataset_role: MeasurementDatasetRole = "raw",
) -> PointDatasetIntent:
    return PointDatasetIntent(
        coordinates=tuple(_column(column) for column in coordinates),
        observables=tuple(
            _column(column, default_unit="ratio") for column in observables
        ),
        dataset_id=dataset_id,
        dataset_role=dataset_role,
    )


def shot_dataset(
    *,
    count_parameter_id: str,
    observables: Sequence[DatasetColumn | str],
    dataset_id: str = "raw-measurements",
    dataset_role: MeasurementDatasetRole = "raw",
) -> ShotDatasetIntent:
    return ShotDatasetIntent(
        count_parameter_id=count_parameter_id,
        observables=tuple(
            _column(column, default_unit="ratio") for column in observables
        ),
        dataset_id=dataset_id,
        dataset_role=dataset_role,
    )


def _measurement_variable(
    column: DatasetColumn,
    *,
    role: MeasurementVariableRole,
    dims: list[str],
    shape: list[int],
    unit: str | None,
) -> MeasurementVariable:
    return MeasurementVariable(
        id=column.id,
        role=role,
        dtype=column.dtype,
        unit=unit,
        dims=dims,
        shape=shape,
        metadata={"label": column.label} if column.label is not None else {},
    )


def _point_count_for_coordinates(
    ctx: ExperimentAuthoringContext,
    coordinates: tuple[DatasetColumn, ...],
    variables: Mapping[str, ExperimentVariable],
) -> int:
    for coordinate_column in coordinates:
        variable = variables.get(coordinate_column.id)
        if variable is None:
            continue
        count = _variable_count(variable)
        if count is not None:
            return count
    ctx.raise_diagnostic(
        "recipe_dataset_point_count_unknown",
        "point dataset requires at least one counted coordinate variable",
        "dataset.coordinates",
    )


def _variable_count(variable: ExperimentVariable) -> int | None:
    if variable.kind == "linspace":
        return variable.count
    if variable.kind == "points" and variable.points is not None:
        return len(variable.points)
    return None


def _variable_unit(
    ctx: ExperimentAuthoringContext,
    variable_id: str,
    variables: Mapping[str, ExperimentVariable],
) -> str | None:
    variable = variables.get(variable_id)
    if variable is None:
        ctx.raise_diagnostic(
            "recipe_dataset_coordinate_unknown",
            f"dataset coordinate {variable_id} is not a variable",
            "dataset.coordinates",
        )
    if variable.kind == "linspace" and variable.start is not None:
        return variable.start.unit
    if variable.kind == "points" and variable.points:
        return variable.points[0].unit
    return None


def _column(
    value: DatasetColumn | str,
    *,
    default_unit: str | None = None,
) -> DatasetColumn:
    if isinstance(value, DatasetColumn):
        return value
    return DatasetColumn(id=value, unit=default_unit)
