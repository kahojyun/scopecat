"""Transient runtime graph for structured experiment execution.

The graph is an internal execution surface. It deliberately has no schema
version, hash, or persistence contract; persisted runs keep the linked
experiment spec, accepted config, data evidence, diagnostics, and compact
execution snapshots instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from scopecat._planning.compute_dependencies import (
    ComputeDependencySummary,
    summarize_compute_dependencies,
)
from scopecat._planning.compute_payloads import resolve_compute_payload_schemas
from scopecat._planning.planner import (
    PlannerPoint,
    PlannerSnapshot,
    build_planner_snapshot,
)
from scopecat._planning.records import RecordPlan
from scopecat._runtime.lowering import (
    compile_collect_instructions,
    compile_desired_state_points,
    compile_point_routes,
    compute_result_payload_id,
    normalize_desired_state,
    resolve_program_state_resources,
    route_constraint_diagnostics,
    runtime_product_binding,
)
from scopecat.experiments import (
    CollectInstructionPlan,
    ComputeNodeSpec,
    ExperimentSpec,
    PointRouteBinding,
    ProductBinding,
    ProgramResourceState,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.parameters import ParameterDerivationSet
from scopecat.relations import ParameterRelationData, Row
from scopecat.results import CoordinateValue, MeasurementDatasetSchema


@dataclass(frozen=True)
class RuntimeComputePayloadPlan:
    """One typed command payload materialized from a compute result."""

    id: str
    schema_id: str


@dataclass(frozen=True)
class RuntimeComputeStep:
    """Point-local pure compute node boundary for future dirty execution."""

    node_id: str
    dependencies: ComputeDependencySummary
    payload: RuntimeComputePayloadPlan | None = None

    @property
    def dirty_inputs(self) -> dict[str, list[str]]:
        return self.dependencies.as_dict()


@dataclass(frozen=True)
class RuntimePoint:
    point_index: int
    point_uid: str
    row: Row
    params: ParameterRelationData
    coordinates: dict[str, CoordinateValue]
    compute_steps: tuple[RuntimeComputeStep, ...]
    route_bindings: tuple[PointRouteBinding, ...]
    desired_state: tuple[ProgramResourceState, ...]
    collect: tuple[CollectInstructionPlan, ...]


@dataclass(frozen=True)
class RuntimeGraph:
    """Internal dependency graph consumed by the execution cursor."""

    experiment_id: str
    point_coordinate_ids: tuple[str, ...]
    points: tuple[RuntimePoint, ...]
    compute_nodes_by_id: dict[str, ComputeNodeSpec]
    compute_dependencies_by_node: dict[str, ComputeDependencySummary]
    records: tuple[RecordPlan, ...]
    product_bindings: tuple[ProductBinding, ...]
    payloads_by_id: dict[str, CommandPayload]
    expected_dataset_schema: MeasurementDatasetSchema | None
    diagnostics: tuple[dict[str, Any], ...]

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def payloads(self) -> tuple[CommandPayload, ...]:
        return tuple(self.payloads_by_id.values())

    @property
    def observable_output_ids(self) -> set[str]:
        return {record.id for record in self.records if record.kind == "observable"}

    @property
    def expected_measurement_indices(self) -> set[int]:
        return {point.point_index for point in self.points}


def build_runtime_graph(
    plan: PlannerSnapshot,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> RuntimeGraph:
    """Lower a plan into the transient runtime graph."""

    product_bindings = [
        runtime_product_binding(record)
        for record in plan.records
        if record.source == "instrument"
    ]
    route_bindings, route_resolution_diagnostics = compile_point_routes(
        plan,
        config=config,
    )
    payload_resolution = resolve_compute_payload_schemas(
        plan.desired_state,
        plan.compute_nodes,
    )
    payload_schemas = payload_resolution.schema_ids
    compute_dependencies_by_node = summarize_compute_dependencies(plan.compute_nodes)
    command_payloads = _expected_command_payload_stubs(
        points=plan.points,
        compute_nodes=plan.compute_nodes,
        payload_schemas=payload_schemas,
    )
    desired_points, state_diagnostics = compile_desired_state_points(
        plan.desired_state,
        command_payload_ids=set(command_payloads),
        unavailable_compute_payload_node_ids=(payload_resolution.unavailable_node_ids),
        route_bindings=route_bindings,
    )
    collect_by_point = compile_collect_instructions(
        point_indices=[point.point_index for point in plan.points],
        product_bindings=product_bindings,
        route_bindings=route_bindings,
    )
    runtime_points: list[RuntimePoint] = []
    normalize_diagnostics: list[dict[str, Any]] = []
    for point in plan.points:
        resolved_desired_state = resolve_program_state_resources(
            desired_points.get(point.point_index, []),
            route_bindings.get(point.point_index, []),
        )
        normalized_desired_state, point_normalize_diagnostics = normalize_desired_state(
            resolved_desired_state,
            point_index=point.point_index,
        )
        normalize_diagnostics.extend(point_normalize_diagnostics)
        runtime_points.append(
            RuntimePoint(
                point_index=point.point_index,
                point_uid=point.point_uid,
                row=point.row,
                params=plan.point_parameters.get(
                    point.point_index,
                    ParameterRelationData(),
                ),
                coordinates=cast(
                    "dict[str, CoordinateValue]",
                    {
                        name: value
                        for name, value in point.row.items()
                        if name in plan.point_coordinate_ids
                    },
                ),
                compute_steps=_runtime_compute_steps(
                    point_index=point.point_index,
                    compute_nodes=plan.compute_nodes,
                    dependencies_by_node=compute_dependencies_by_node,
                    payload_schemas=payload_schemas,
                ),
                route_bindings=tuple(route_bindings.get(point.point_index, [])),
                desired_state=tuple(normalized_desired_state),
                collect=tuple(collect_by_point.get(point.point_index, [])),
            )
        )
    route_constraint_diagnostics_result = route_constraint_diagnostics(
        cast("Any", runtime_points),
        group_resource_limits=_group_resource_limits(config),
        channel_route_port_limits=_channel_route_port_limits(config),
    )

    return RuntimeGraph(
        experiment_id=plan.experiment_id,
        point_coordinate_ids=tuple(plan.point_coordinate_ids),
        points=tuple(runtime_points),
        compute_nodes_by_id={node.id: node for node in plan.compute_nodes},
        compute_dependencies_by_node=compute_dependencies_by_node,
        records=tuple(plan.records),
        product_bindings=tuple(product_bindings),
        payloads_by_id=command_payloads,
        expected_dataset_schema=plan.expected_dataset_schema,
        diagnostics=(
            *plan.diagnostics,
            *route_resolution_diagnostics,
            *payload_resolution.diagnostics,
            *state_diagnostics,
            *normalize_diagnostics,
            *route_constraint_diagnostics_result,
        ),
    )


def build_runtime_graph_for_experiment(
    experiment: ExperimentSpec,
    params: ParameterRelationData | ParameterViewSnapshot,
    *,
    config: ConfigProfileSnapshot | None = None,
    derivations: ParameterDerivationSet | None = None,
    allow_table_row_changes: bool = False,
) -> RuntimeGraph:
    """Build the transient runtime graph without exposing planner IR upstream."""

    return build_runtime_graph(
        build_planner_snapshot(
            experiment,
            params,
            derivations=derivations,
            allow_table_row_changes=allow_table_row_changes,
        ),
        config=config,
    )


def _group_resource_limits(
    config: ConfigProfileSnapshot | None,
) -> dict[str, int | None]:
    if config is None:
        return {}
    return {group.id: group.max_resources_per_point for group in config.topology.groups}


def _channel_route_port_limits(
    config: ConfigProfileSnapshot | None,
) -> dict[str, int | None]:
    if config is None:
        return {}
    return {
        channel.id: channel.max_route_ports_per_point
        for channel in config.topology.channels
    }


def _expected_command_payload_stubs(
    *,
    points: list[PlannerPoint],
    compute_nodes: list[ComputeNodeSpec],
    payload_schemas: dict[str, str],
) -> dict[str, CommandPayload]:
    payloads: dict[str, CommandPayload] = {}
    for point in points:
        for node in compute_nodes:
            schema_id = payload_schemas.get(node.id)
            if schema_id is None:
                continue
            payload_id = compute_result_payload_id(node.id, point.point_index)
            payloads[payload_id] = CommandPayload(
                id=payload_id,
                schema_id=schema_id,
                metadata={
                    "compute_node_id": node.id,
                    "point_index": point.point_index,
                    "runtime_payload": "deferred",
                },
                payload=object(),
            )
    return payloads


def _runtime_compute_steps(
    *,
    point_index: int,
    compute_nodes: list[ComputeNodeSpec],
    dependencies_by_node: dict[str, ComputeDependencySummary],
    payload_schemas: dict[str, str],
) -> tuple[RuntimeComputeStep, ...]:
    return tuple(
        RuntimeComputeStep(
            node_id=node.id,
            dependencies=dependencies_by_node.get(node.id, ComputeDependencySummary()),
            payload=(
                RuntimeComputePayloadPlan(
                    id=compute_result_payload_id(node.id, point_index),
                    schema_id=payload_schemas[node.id],
                )
                if node.id in payload_schemas
                else None
            ),
        )
        for node in compute_nodes
    )


__all__ = [
    "RuntimeComputePayloadPlan",
    "RuntimeComputeStep",
    "RuntimeGraph",
    "RuntimePoint",
    "build_runtime_graph",
    "build_runtime_graph_for_experiment",
]
