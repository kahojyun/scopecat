"""Internal builders for high-level experiment preview summaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from scopecat._planning.compute_dependencies import (
    ComputeDependencySummary,
    summarize_compute_dependencies,
)
from scopecat._planning.planner import PlannerSnapshot, build_planner_snapshot
from scopecat._runtime.graph import RuntimeGraph, build_runtime_graph_for_experiment
from scopecat._runtime.lowering import compute_result_payload_id
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import (
    ExperimentSpec,
    PointRouteBinding,
    ProgramStateValue,
)
from scopecat.models.config import ConfigProfileSnapshot, RoutingChannelBinding
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.parameters import ParameterDerivationSet
from scopecat.preview import (
    ExperimentPreview,
    ExperimentPreviewChannelBinding,
    ExperimentPreviewComputeStep,
    ExperimentPreviewPayload,
    ExperimentPreviewPoint,
    ExperimentPreviewRecord,
    ExperimentPreviewResolvedRoute,
    ExperimentPreviewRoute,
    ExperimentPreviewRuntimeSummary,
    ExperimentPreviewStateChange,
    ExperimentPreviewStateField,
)
from scopecat.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class _PreviewRouteIntentSummary:
    port_id: str
    capabilities: tuple[str, ...]
    entity_expr_count: int
    fixed_resource: str | None


@dataclass(frozen=True)
class _PreviewStateChangeSummary:
    point_index: int
    resource: str
    field: str
    before: object | None
    after: object


@dataclass(frozen=True)
class _PreviewRecordSummary:
    id: str
    kind: str
    source: str
    resource: str | None
    capability: str | None
    unit: str | None
    dtype: str
    dims: tuple[str, ...]
    shape: tuple[int, ...]


@dataclass(frozen=True)
class _PreviewPointSummary:
    point_index: int
    point_uid: str
    row: dict[str, object]


@dataclass(frozen=True)
class _PreviewSnapshot:
    experiment_id: str
    experiment_kind: str
    schema: MeasurementDatasetSchema | None
    coordinate_ids: tuple[str, ...]
    points: tuple[_PreviewPointSummary, ...]
    records: tuple[_PreviewRecordSummary, ...]
    state_changes: tuple[_PreviewStateChangeSummary, ...]
    route_intents: tuple[_PreviewRouteIntentSummary, ...]
    resolved_routes_by_port: dict[str, tuple[ExperimentPreviewResolvedRoute, ...]]
    state_fields: tuple[ExperimentPreviewStateField, ...]
    payloads: tuple[ExperimentPreviewPayload, ...]
    compute_steps: tuple[ExperimentPreviewComputeStep, ...]
    route_count: int
    state_field_count: int
    compute_node_count: int
    dataset_dimensions: dict[str, int]
    primary_observables: tuple[str, ...]


def build_experiment_preview(
    experiment: ExperimentSpec,
    parameter_view: ParameterViewSnapshot,
    *,
    config: ConfigProfileSnapshot | None = None,
    derivations: ParameterDerivationSet | None = None,
) -> tuple[ExperimentPreview, tuple[Diagnostic, ...]]:
    plan = build_planner_snapshot(
        experiment,
        parameter_view,
        derivations=derivations,
    )
    graph = (
        build_runtime_graph_for_experiment(
            experiment,
            parameter_view,
            config=config,
            derivations=derivations,
        )
        if config is not None
        else None
    )
    diagnostics: tuple[dict[str, Any], ...] = (
        graph.diagnostics if graph is not None else tuple(plan.diagnostics)
    )
    return _preview_from_snapshot(_snapshot_from_lowering(plan, graph=graph)), tuple(
        Diagnostic.model_validate(diagnostic) for diagnostic in diagnostics
    )


def _snapshot_from_lowering(
    plan: PlannerSnapshot,
    *,
    graph: RuntimeGraph | None = None,
) -> _PreviewSnapshot:
    dataset_schema = plan.expected_dataset_schema
    coordinate_ids = tuple(
        dataset_schema.primary_coordinates
        if dataset_schema is not None
        else plan.point_coordinate_ids
    )
    state_fields = _preview_state_fields(graph)
    payloads = _preview_payloads(plan, graph=graph)
    compute_steps = _preview_compute_steps(plan, graph=graph)
    return _PreviewSnapshot(
        experiment_id=plan.experiment_id,
        experiment_kind=plan.experiment_kind,
        schema=dataset_schema,
        coordinate_ids=coordinate_ids,
        points=tuple(
            _PreviewPointSummary(
                point_index=point.point_index,
                point_uid=point.point_uid,
                row=dict(point.row),
            )
            for point in plan.points
        ),
        records=tuple(
            _PreviewRecordSummary(
                id=record.id,
                kind=record.kind,
                source=record.source,
                resource=record.resource,
                capability=record.capability,
                unit=record.unit,
                dtype=record.dtype,
                dims=tuple(record.dims),
                shape=tuple(record.shape),
            )
            for record in plan.records
        ),
        state_changes=tuple(
            _PreviewStateChangeSummary(
                point_index=change.point_index,
                resource=change.resource,
                field=change.field,
                before=change.before,
                after=change.after,
            )
            for change in plan.state_patches
        ),
        route_intents=tuple(
            _PreviewRouteIntentSummary(
                port_id=route.port_id,
                capabilities=tuple(route.capabilities),
                entity_expr_count=len(route.entity_exprs),
                fixed_resource=route.resource_id,
            )
            for route in plan.route_intents
        ),
        resolved_routes_by_port={
            route.port_id: _resolved_route_preview(route.port_id, graph=graph)
            for route in plan.route_intents
        },
        state_fields=state_fields,
        payloads=payloads,
        compute_steps=compute_steps,
        route_count=len(plan.route_intents),
        state_field_count=_preview_state_field_count(
            plan=plan,
            graph=graph,
        ),
        compute_node_count=len(plan.compute_nodes),
        dataset_dimensions=(
            {
                dimension.id: dimension.size
                for dimension in dataset_schema.dimensions
                if dimension.size is not None
            }
            if dataset_schema is not None
            else {}
        ),
        primary_observables=(
            tuple(dataset_schema.primary_observables)
            if dataset_schema is not None
            else tuple(record.id for record in plan.records)
        ),
    )


def _preview_from_snapshot(
    snapshot: _PreviewSnapshot,
) -> ExperimentPreview:
    return ExperimentPreview(
        experiment_id=snapshot.experiment_id,
        experiment_kind=snapshot.experiment_kind,
        point_count=len(snapshot.points),
        schema=snapshot.schema,
        coordinate_ids=snapshot.coordinate_ids,
        points=tuple(
            ExperimentPreviewPoint(
                point_index=point.point_index,
                point_uid=point.point_uid,
                coordinates={
                    coordinate_id: point.row[coordinate_id]
                    for coordinate_id in snapshot.coordinate_ids
                    if coordinate_id in point.row
                },
            )
            for point in snapshot.points
        ),
        records=tuple(
            ExperimentPreviewRecord(
                id=record.id,
                kind=record.kind,
                source=record.source,
                resource=record.resource,
                capability=record.capability,
                unit=record.unit,
                dtype=record.dtype,
                dims=tuple(record.dims),
                shape=tuple(record.shape),
            )
            for record in snapshot.records
        ),
        state_changes=tuple(
            ExperimentPreviewStateChange(
                point_index=change.point_index,
                resource=change.resource,
                field=change.field,
                before=change.before,
                after=change.after,
            )
            for change in snapshot.state_changes
        ),
        routes=tuple(
            ExperimentPreviewRoute(
                port_id=route.port_id,
                capabilities=tuple(route.capabilities),
                entity_expr_count=route.entity_expr_count,
                fixed_resource=route.fixed_resource,
                resolved=snapshot.resolved_routes_by_port.get(route.port_id, ()),
            )
            for route in snapshot.route_intents
        ),
        state_fields=snapshot.state_fields,
        payloads=snapshot.payloads,
        compute_steps=snapshot.compute_steps,
        runtime=ExperimentPreviewRuntimeSummary(
            route_count=snapshot.route_count,
            state_field_count=snapshot.state_field_count,
            compute_node_count=snapshot.compute_node_count,
            compute_step_count=len(snapshot.compute_steps),
            payload_count=len(snapshot.payloads),
        ),
        dataset_dimensions=snapshot.dataset_dimensions,
        primary_observables=snapshot.primary_observables,
    )


def _resolved_route_preview(
    port_id: str,
    *,
    graph: RuntimeGraph | None,
) -> tuple[ExperimentPreviewResolvedRoute, ...]:
    if graph is None:
        return ()
    resolved: list[ExperimentPreviewResolvedRoute] = []
    for point in graph.points:
        for route in point.route_bindings:
            if route.port_id != port_id:
                continue
            resolved.append(
                ExperimentPreviewResolvedRoute(
                    point_index=point.point_index,
                    port_id=route.port_id,
                    resource_id=route.resource_id,
                    entity_ids=tuple(route.entity_ids),
                    product_axis_order=tuple(route.product_axis_order),
                    channel_bindings=tuple(
                        ExperimentPreviewChannelBinding(
                            entity_id=binding.entity_id,
                            channel_id=binding.channel_id,
                            line_id=binding.line_id,
                            capability=binding.capability,
                            group_ids=tuple(binding.group_ids),
                        )
                        for binding in route.channel_bindings
                    ),
                )
            )
    return tuple(resolved)


def _preview_state_fields(
    graph: RuntimeGraph | None,
) -> tuple[ExperimentPreviewStateField, ...]:
    if graph is None:
        return ()
    fields: list[ExperimentPreviewStateField] = []
    for point in graph.points:
        for state in point.desired_state:
            for field in state.fields:
                fields.append(
                    ExperimentPreviewStateField(
                        point_index=point.point_index,
                        resource_id=state.resource_id,
                        capability_id=state.capability_id,
                        field_path=field.field_path,
                        value_kind=field.value.kind,
                        value=_preview_state_value(field.value),
                        payload_id=field.value.payload_id,
                        channel_bindings=(
                            _preview_channel_bindings(field.channel_bindings)
                            or _state_channel_bindings(
                                point.route_bindings,
                                resource_id=state.resource_id,
                                capability_id=state.capability_id,
                            )
                        ),
                    )
                )
    return tuple(fields)


def _preview_state_value(value: ProgramStateValue) -> object | None:
    if value.quantity is not None:
        return value.quantity
    if value.value is not None:
        return value.value
    return None


def _preview_channel_bindings(
    bindings: Sequence[RoutingChannelBinding],
) -> tuple[ExperimentPreviewChannelBinding, ...]:
    return tuple(
        ExperimentPreviewChannelBinding(
            entity_id=binding.entity_id,
            channel_id=binding.channel_id,
            line_id=binding.line_id,
            capability=binding.capability,
            group_ids=tuple(binding.group_ids),
        )
        for binding in bindings
    )


def _state_channel_bindings(
    routes: Sequence[PointRouteBinding],
    *,
    resource_id: str,
    capability_id: str,
) -> tuple[ExperimentPreviewChannelBinding, ...]:
    channel_bindings: list[ExperimentPreviewChannelBinding] = []
    seen: set[tuple[str, str, str | None, str | None, tuple[str, ...]]] = set()
    for route in routes:
        if route.resource_id != resource_id or capability_id not in route.capabilities:
            continue
        for binding in route.channel_bindings:
            key = (
                binding.entity_id,
                binding.channel_id,
                binding.line_id,
                binding.capability,
                tuple(binding.group_ids),
            )
            if key in seen:
                continue
            seen.add(key)
            channel_bindings.append(
                ExperimentPreviewChannelBinding(
                    entity_id=binding.entity_id,
                    channel_id=binding.channel_id,
                    line_id=binding.line_id,
                    capability=binding.capability,
                    group_ids=tuple(binding.group_ids),
                )
            )
    return tuple(channel_bindings)


def _preview_state_field_count(
    *,
    plan: PlannerSnapshot,
    graph: RuntimeGraph | None,
) -> int:
    if graph is None:
        return len(plan.desired_state)
    return sum(
        len(state.fields) for point in graph.points for state in point.desired_state
    )


def _preview_payloads(
    plan: PlannerSnapshot,
    *,
    graph: RuntimeGraph | None,
) -> tuple[ExperimentPreviewPayload, ...]:
    fields_by_node: dict[tuple[str, str], set[str]] = {}
    dependencies_by_node = (
        graph.compute_dependencies_by_node
        if graph is not None
        else summarize_compute_dependencies(plan.compute_nodes)
    )
    for state in plan.desired_state:
        for node_id, payload_kind in _compute_result_references(state.value):
            fields_by_node.setdefault((node_id, payload_kind), set()).add(state.field)
    return tuple(
        ExperimentPreviewPayload(
            node_id=node_id,
            kind=payload_kind,
            state_fields=tuple(sorted(fields)),
            dependencies=_preview_dependency_map(dependencies_by_node.get(node_id)),
        )
        for (node_id, payload_kind), fields in sorted(fields_by_node.items())
    )


def _preview_compute_steps(
    plan: PlannerSnapshot,
    *,
    graph: RuntimeGraph | None,
) -> tuple[ExperimentPreviewComputeStep, ...]:
    if graph is not None:
        return tuple(
            ExperimentPreviewComputeStep(
                point_index=point.point_index,
                node_id=step.node_id,
                payload_id=step.payload_id,
                payload_kind=step.payload_kind,
                dependencies=_preview_dependency_map(step.dependencies),
            )
            for point in graph.points
            for step in point.compute_steps
        )
    dependencies_by_node = summarize_compute_dependencies(plan.compute_nodes)
    payload_kinds = _payload_kinds_from_state(plan)
    return tuple(
        ExperimentPreviewComputeStep(
            point_index=point.point_index,
            node_id=node.id,
            payload_id=(
                compute_result_payload_id(node.id, point.point_index)
                if node.id in payload_kinds
                else None
            ),
            payload_kind=payload_kinds.get(node.id),
            dependencies=_preview_dependency_map(dependencies_by_node.get(node.id)),
        )
        for point in plan.points
        for node in plan.compute_nodes
    )


def _payload_kinds_from_state(plan: PlannerSnapshot) -> dict[str, str]:
    payload_kinds: dict[str, str] = {}
    for state in plan.desired_state:
        for node_id, payload_kind in _compute_result_references(state.value):
            payload_kinds.setdefault(node_id, payload_kind)
    return payload_kinds


def _preview_dependency_map(
    summary: ComputeDependencySummary | None,
) -> dict[str, tuple[str, ...]]:
    if summary is None:
        return {}
    return {key: tuple(value) for key, value in summary.as_dict().items()}


def _compute_result_references(value: object) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        if mapping.get("kind") == "compute_result":
            node_id = mapping.get("node_id")
            payload_kind = mapping.get("payload_kind")
            if isinstance(node_id, str) and isinstance(payload_kind, str):
                refs.append((node_id, payload_kind))
        for child in mapping.values():
            refs.extend(_compute_result_references(child))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values = cast("Sequence[object]", value)
        for child in values:
            refs.extend(_compute_result_references(child))
    return refs


__all__ = ["build_experiment_preview"]
