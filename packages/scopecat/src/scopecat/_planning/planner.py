"""Transient planner snapshot builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, cast

from pydantic import BaseModel

from scopecat._planning.diagnostics import (
    PlanningDiagnosticError,
    planning_diagnostic,
)
from scopecat._planning.hashes import payload_hash
from scopecat._planning.parameter_patches import ParameterPatchPlanRecord
from scopecat._planning.records import (
    RecordPlan,
    expected_dataset_schema,
    plan_records,
    point_coordinate_ids,
    validate_record_plan,
)
from scopecat._planning.state import (
    StatePatchRecord,
    StateRecord,
    state_patches,
    validate_state_records,
)
from scopecat.experiments import ComputeNodeSpec, ExperimentSpec, ResourceRouteIntent
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.parameters import ParameterDerivationSet
from scopecat.relations import EvalContext, ParameterRelationData, Row
from scopecat.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class PlannerPoint:
    point_index: int
    point_uid: str
    row: Row


@dataclass(frozen=True)
class PlannerSnapshot:
    """Transient planner output for a closed experiment segment."""

    experiment_id: str
    experiment_kind: str
    points: list[PlannerPoint]
    parameter_patches: list[ParameterPatchPlanRecord]
    desired_state: list[StateRecord]
    state_patches: list[StatePatchRecord]
    point_coordinate_ids: list[str] = field(default_factory=list)
    route_intents: list[ResourceRouteIntent] = field(default_factory=list)
    compute_nodes: list[ComputeNodeSpec] = field(default_factory=list)
    records: list[RecordPlan] = field(default_factory=list)
    expected_dataset_schema: MeasurementDatasetSchema | None = None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    point_parameters: dict[int, ParameterRelationData] = field(default_factory=dict)


def build_planner_snapshot(
    spec: ExperimentSpec,
    params: ParameterRelationData | ParameterViewSnapshot,
    *,
    derivations: ParameterDerivationSet | None = None,
    allow_table_row_changes: bool = False,
) -> PlannerSnapshot:
    diagnostics: list[dict[str, Any]] = []
    if isinstance(params, ParameterViewSnapshot):
        diagnostics.extend(params.diagnostics)
    relation_params = (
        params
        if isinstance(params, ParameterRelationData)
        else ParameterRelationData.from_parameter_view(params)
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
        PlannerPoint(
            point_index=point_index,
            point_uid=_point_uid(row),
            row=row,
        )
        for point_index, row in enumerate(point_rows)
    ]
    patch_records: list[ParameterPatchPlanRecord] = []
    state_records: list[StateRecord] = []
    point_parameters: dict[int, ParameterRelationData] = {}

    for point in points:
        point_params = relation_params.model_copy(deep=True)
        point_ctx = EvalContext(params=point_params, row=point.row)
        patch_failed = False
        for patch_index, patch in enumerate(spec.params):
            try:
                patch_records.append(
                    patch.apply(
                        point_index=point.point_index,
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
                            f"{point.point_index}: {error}"
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
                        f"{point.point_index}: {error}"
                    ),
                    "parameter_derivations",
                )
            )
            continue
        point_parameters[point.point_index] = point_params.model_copy(deep=True)
        patched_ctx = EvalContext(params=point_params, row=point.row)
        for state_index, state in enumerate(spec.state):
            try:
                state_records.extend(
                    state.evaluate(point_index=point.point_index, ctx=patched_ctx)
                )
            except Exception as error:
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        "experiment_state_evaluation_failed",
                        (
                            f"experiment state binding failed for point "
                            f"{point.point_index}: {error}"
                        ),
                        f"state.{state_index}",
                    )
                )

    diagnostics.extend(validate_state_records(state_records))
    plan_record_outputs = plan_records(spec.records, point_count=len(points))
    record_diagnostics = validate_record_plan(plan_record_outputs)
    diagnostics.extend(record_diagnostics)
    plan_point_coordinate_ids = point_coordinate_ids(points)
    plan_expected_dataset_schema = (
        None
        if record_diagnostics
        else expected_dataset_schema(
            experiment_id=spec.id,
            points=points,
            records=plan_record_outputs,
        )
    )
    state_patch_records = state_patches(state_records)
    return PlannerSnapshot(
        experiment_id=spec.id,
        experiment_kind=spec.kind,
        point_coordinate_ids=plan_point_coordinate_ids,
        points=points,
        route_intents=list(spec.route_intents),
        parameter_patches=patch_records,
        compute_nodes=list(spec.compute_nodes),
        desired_state=state_records,
        state_patches=state_patch_records,
        records=plan_record_outputs,
        expected_dataset_schema=plan_expected_dataset_schema,
        diagnostics=diagnostics,
        point_parameters=point_parameters,
    )


def _point_uid(row: Row) -> str:
    return payload_hash({"row": _json_safe(row)})


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        return {key: _json_safe(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        return [_json_safe(item) for item in sequence]
    return value


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


__all__ = ["PlannerPoint", "PlannerSnapshot", "build_planner_snapshot"]
