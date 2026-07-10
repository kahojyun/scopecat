"""Transient planner snapshot builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, cast

from pydantic import BaseModel

from scopecat._compiler.program import (
    ComputeNodeSpec,
    LinkedProgram,
    ResourceRouteIntent,
)
from scopecat._planning.diagnostics import (
    PlanningDiagnosticError,
    planning_diagnostic,
)
from scopecat._planning.hashes import payload_hash
from scopecat._planning.parameter_overlays import apply_point_parameter_overlay
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
from scopecat._relations import EvalContext, ParameterRelationData, Row
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
    spec: LinkedProgram,
    params: ParameterRelationData,
) -> PlannerSnapshot:
    diagnostics: list[dict[str, Any]] = []
    try:
        point_rows = spec.points.evaluate(params)
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
            point_uid=_point_uid(point_index, row),
            row=row,
        )
        for point_index, row in enumerate(point_rows)
    ]
    state_records: list[StateRecord] = []
    point_parameters: dict[int, ParameterRelationData] = {}

    for point in points:
        point_params = params.model_copy(deep=True)
        point_ctx = EvalContext(params=point_params, row=point.row)
        overlay_failed = False
        for overlay_index, overlay in enumerate(spec.parameter_overlays):
            try:
                apply_point_parameter_overlay(
                    overlay,
                    ctx=point_ctx,
                    params=point_params,
                )
            except PlanningDiagnosticError as error:
                overlay_failed = True
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        error.code,
                        str(error),
                        f"parameter_overlays.{overlay_index}",
                    )
                )
            except Exception as error:
                overlay_failed = True
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        "experiment_parameter_overlay_failed",
                        (
                            f"experiment parameter overlay failed for point "
                            f"{point.point_index}: {error}"
                        ),
                        f"parameter_overlays.{overlay_index}",
                    )
                )
        if overlay_failed:
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
        compute_nodes=list(spec.compute_nodes),
        desired_state=state_records,
        state_patches=state_patch_records,
        records=plan_record_outputs,
        expected_dataset_schema=plan_expected_dataset_schema,
        diagnostics=diagnostics,
        point_parameters=point_parameters,
    )


def _point_uid(point_index: int, row: Row) -> str:
    """Identify one point occurrence, including duplicate coordinate rows."""

    return payload_hash({"point_index": point_index, "row": _json_safe(row)})


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


__all__ = ["PlannerPoint", "PlannerSnapshot", "build_planner_snapshot"]
