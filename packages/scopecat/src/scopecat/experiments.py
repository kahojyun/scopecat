"""experiment kernel and planner.

The kernel is intentionally small and mirrors the accepted shape:

``points -> params -> state -> acquire``

This module is the durable experiment path for production planning and
execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scopecat._planning_acquisition import (
    AcquisitionPlan,
    AcquisitionRecordMode,
    AcquisitionSpec,
    ObservationSpec,
    ObservationSpecKind,
    ResultIntent,
    estimated_records,
    expected_dataset_schema,
    point_coordinate_ids,
    result_intents,
    validate_acquisition_plan,
)
from scopecat._planning_diagnostics import (
    PlanningDiagnosticError,
    planning_diagnostic,
)
from scopecat._planning_hashes import (
    PLAN_IMPLEMENTATION_ID,
    PLAN_IMPLEMENTATION_VERSION,
    payload_hash,
    plan_content_hash,
)
from scopecat._planning_parameter_patches import (
    ParameterPatchPlanRecord,
    ParameterPatchSpec,
)
from scopecat._planning_state import (
    StatePatchRecord,
    StateRecord,
    StateSpec,
    state_patches,
    validate_asset_references,
    validate_state_records,
)
from scopecat.models.artifact import ExperimentAsset
from scopecat.models.parameter import (
    ParameterBuildSnapshot,
)
from scopecat.parameters import ParameterDerivationSet
from scopecat.relations import (
    EvalContext,
    ParameterRelationData,
    RelationExpr,
    Row,
    ScalarExpr,
    as_scalar_expr,
    col,
    grid,
    param,
)
from scopecat.relations import (
    table as parameter_table_relation,
)
from scopecat.results import (
    MeasurementDatasetSchema,
)


class ExperimentSpec(BaseModel):
    """Durable experiment recipe."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: str = "scopecat.experiment_spec.v1"
    id: str
    kind: str
    points: RelationExpr
    params: list[ParameterPatchSpec] = Field(default_factory=list)
    state: list[StateSpec] = Field(default_factory=list)
    acquire: AcquisitionSpec
    assets: list[ExperimentAsset] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_id: int
    row: Row


class PlanSnapshot(BaseModel):
    """Durable experiment plan snapshot produced by `plan_experiment`."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: str = "scopecat.plan_snapshot.v1"
    experiment_id: str
    experiment_kind: str
    experiment_hash: str
    parameter_build_id: str | None = None
    parameter_build_hash: str | None = None
    content_hash: str
    plan_implementation_id: str
    plan_implementation_version: str
    point_coordinate_ids: list[str] = Field(default_factory=list)
    points: list[PointRecord]
    parameter_patches: list[ParameterPatchPlanRecord]
    desired_state: list[StateRecord]
    state_patches: list[StatePatchRecord]
    acquisition: AcquisitionPlan
    result_intents: list[ResultIntent] = Field(default_factory=list)
    expected_dataset_schema: MeasurementDatasetSchema | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    assets: list[ExperimentAsset] = Field(default_factory=list)


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
class ParameterScan:
    """Authoring fragment for a point relation plus matching parameter patch."""

    points: RelationExpr
    patch: ParameterPatchSpec

    def params(self) -> list[ParameterPatchSpec]:
        return [self.patch]


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


def scan_parameter(
    row: ParameterRowSelector,
    column: str,
    source: object,
    *,
    axis: str | None = None,
) -> ParameterScan:
    axis_id = axis or column
    return ParameterScan(
        points=grid(**{axis_id: source}),
        patch=row.patch(**{column: col(axis_id)}),
    )


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


def set_state(resource: object, field: str, value: object) -> StateSpec:
    return StateSpec(
        kind="set",
        resource=as_scalar_expr(resource),
        field=field,
        value=as_scalar_expr(value),
    )


def bind_each(relation: RelationExpr, *state: StateSpec) -> StateSpec:
    return StateSpec(kind="for_each", relation=relation, state=list(state))


def acquire(
    kind: str,
    *,
    shots: int = 1,
    repetitions: int = 1,
    record: AcquisitionRecordMode = "point",
    dimensions: list[str] | None = None,
    channels: list[str] | None = None,
    observations: list[ObservationSpec] | None = None,
) -> AcquisitionSpec:
    return AcquisitionSpec(
        kind=kind,
        shots=shots,
        repetitions=repetitions,
        record=record,
        dimensions=dimensions or [],
        channels=channels or [],
        observations=observations or [],
    )


def observe(
    id: str,  # noqa: A002
    *,
    kind: ObservationSpecKind = "observable",
    unit: str | None = None,
    resource: str | None = None,
) -> ObservationSpec:
    return ObservationSpec(id=id, kind=kind, unit=unit, resource=resource)


def point(
    id: str,  # noqa: A002
    *,
    unit: str | None = None,
    resource: str | None = None,
) -> ObservationSpec:
    return observe(id, kind="observable", unit=unit, resource=resource)


def trace(
    id: str,  # noqa: A002
    *,
    unit: str | None = None,
    resource: str | None = None,
) -> ObservationSpec:
    return observe(id, kind="artifact", unit=unit, resource=resource)


def experiment(
    *,
    id: str,  # noqa: A002
    kind: str,
    points: RelationExpr,
    params: list[ParameterPatchSpec] | None = None,
    state: list[StateSpec] | None = None,
    acquire: AcquisitionSpec,
    assets: list[ExperimentAsset] | None = None,
) -> ExperimentSpec:
    return ExperimentSpec(
        id=id,
        kind=kind,
        points=points,
        params=params or [],
        state=state or [],
        acquire=acquire,
        assets=assets or [],
    )


def plan_experiment(
    spec: ExperimentSpec,
    params: ParameterRelationData | ParameterBuildSnapshot,
    *,
    derivations: ParameterDerivationSet | None = None,
    allow_table_row_changes: bool = False,
) -> PlanSnapshot:
    experiment_hash = payload_hash(spec.model_dump(mode="json"))
    parameter_build_id = None
    parameter_build_hash = None
    diagnostics: list[dict[str, Any]] = []
    if isinstance(params, ParameterBuildSnapshot):
        parameter_build_id = params.id
        parameter_build_hash = params.content_hash
        diagnostics.extend(params.diagnostics)
    relation_params = (
        params
        if isinstance(params, ParameterRelationData)
        else ParameterRelationData.from_build_snapshot(params)
    )
    try:
        point_rows = spec.points.evaluate(relation_params)
    except Exception as error:
        point_rows = []
        diagnostics.append(
            planning_diagnostic(
                "error",
                "experiment_points_evaluation_failed",
                f"experiment point relation failed: {error}",
                "points",
            )
        )
    points = [
        PointRecord(point_id=point_id, row=row)
        for point_id, row in enumerate(point_rows)
    ]
    patch_records: list[ParameterPatchPlanRecord] = []
    state_records: list[StateRecord] = []

    for point in points:
        point_params = relation_params.model_copy(deep=True)
        point_ctx = EvalContext(params=point_params, row=point.row)
        patch_failed = False
        for patch_index, patch in enumerate(spec.params):
            try:
                patch_records.append(
                    patch.apply(
                        point_id=point.point_id,
                        ctx=point_ctx,
                        params=point_params,
                        allow_table_row_changes=allow_table_row_changes,
                    )
                )
            except PlanningDiagnosticError as error:
                patch_failed = True
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        error.code,
                        str(error),
                        f"params.{patch_index}",
                    )
                )
            except Exception as error:
                patch_failed = True
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        "experiment_parameter_patch_failed",
                        (
                            f"experiment parameter patch failed for point "
                            f"{point.point_id}: {error}"
                        ),
                        f"params.{patch_index}",
                    )
                )
        if patch_failed:
            continue
        try:
            _refresh_parameter_derivations(point_params, derivations)
        except Exception as error:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_parameter_derivation_failed",
                    (
                        f"experiment parameter derivation failed for point "
                        f"{point.point_id}: {error}"
                    ),
                    "parameter_derivations",
                )
            )
            continue
        patched_ctx = EvalContext(params=point_params, row=point.row)
        for state_index, state in enumerate(spec.state):
            try:
                state_records.extend(
                    state.evaluate(point_id=point.point_id, ctx=patched_ctx)
                )
            except Exception as error:
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        "experiment_state_evaluation_failed",
                        (
                            f"experiment state binding failed for point "
                            f"{point.point_id}: {error}"
                        ),
                        f"state.{state_index}",
                    )
                )

    diagnostics.extend(validate_state_records(state_records))
    diagnostics.extend(
        validate_asset_references(assets=spec.assets, state_records=state_records)
    )
    acquisition = AcquisitionPlan(
        kind=spec.acquire.kind,
        shots=spec.acquire.shots,
        repetitions=spec.acquire.repetitions,
        record=spec.acquire.record,
        dimensions=spec.acquire.dimensions,
        channels=spec.acquire.channels,
        observations=spec.acquire.observations,
        estimated_records=estimated_records(spec.acquire, len(points)),
    )
    acquisition_diagnostics = validate_acquisition_plan(acquisition)
    diagnostics.extend(acquisition_diagnostics)
    plan_result_intents = result_intents(acquisition)
    plan_point_coordinate_ids = point_coordinate_ids(points)
    plan_expected_dataset_schema = (
        None
        if acquisition_diagnostics
        else expected_dataset_schema(
            experiment_id=spec.id,
            points=points,
            acquisition=acquisition,
            result_intents=plan_result_intents,
        )
    )
    state_patch_records = state_patches(state_records)
    content_hash = plan_content_hash(
        experiment_id=spec.id,
        experiment_kind=spec.kind,
        experiment_hash=experiment_hash,
        parameter_build_id=parameter_build_id,
        parameter_build_hash=parameter_build_hash,
        point_coordinate_ids=plan_point_coordinate_ids,
        points=points,
        parameter_patches=patch_records,
        desired_state=state_records,
        state_patches=state_patch_records,
        acquisition=acquisition,
        result_intents=plan_result_intents,
        expected_dataset_schema=plan_expected_dataset_schema,
        diagnostics=diagnostics,
        assets=spec.assets,
    )
    return PlanSnapshot(
        experiment_id=spec.id,
        experiment_kind=spec.kind,
        experiment_hash=experiment_hash,
        parameter_build_id=parameter_build_id,
        parameter_build_hash=parameter_build_hash,
        content_hash=content_hash,
        plan_implementation_id=PLAN_IMPLEMENTATION_ID,
        plan_implementation_version=PLAN_IMPLEMENTATION_VERSION,
        point_coordinate_ids=plan_point_coordinate_ids,
        points=points,
        parameter_patches=patch_records,
        desired_state=state_records,
        state_patches=state_patch_records,
        acquisition=acquisition,
        result_intents=plan_result_intents,
        expected_dataset_schema=plan_expected_dataset_schema,
        diagnostics=diagnostics,
        assets=spec.assets,
    )


def _refresh_parameter_derivations(
    params: ParameterRelationData,
    derivations: ParameterDerivationSet | None,
) -> None:
    if derivations is None:
        return
    scalars, tables = derivations.evaluate(params)
    for scalar in scalars:
        params.scalars[scalar.id] = scalar.quantity
    for table in tables:
        params.tables[table.id] = [dict(row) for row in table.rows]


def _axis_name(prefix: str, resource: str) -> str:
    suffix = "".join(char if char.isalnum() else "_" for char in resource).strip("_")
    if suffix == "":
        msg = f"resource {resource!r} cannot produce a local override axis"
        raise ValueError(msg)
    return f"{prefix}_{suffix}"


ExperimentSpec.model_rebuild()

__all__ = [
    "AcquisitionPlan",
    "AcquisitionSpec",
    "ExperimentSpec",
    "LocalOverrides",
    "ObservationSpec",
    "ParameterPatchPlanRecord",
    "ParameterPatchSpec",
    "ParameterRowSelector",
    "ParameterScan",
    "PlanSnapshot",
    "PointRecord",
    "ResultIntent",
    "StatePatchRecord",
    "StateRecord",
    "StateSpec",
    "acquire",
    "bind_each",
    "configure",
    "delete_param_rows",
    "experiment",
    "insert_param_rows",
    "local_overrides",
    "local_scan",
    "observe",
    "param_row",
    "plan_experiment",
    "point",
    "rows",
    "scan_parameter",
    "set_param",
    "set_state",
    "trace",
    "update_param_rows",
]
