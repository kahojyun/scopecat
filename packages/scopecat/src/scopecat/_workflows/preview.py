"""Pure projections from the config-bound plan into user-visible summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat._compiler.bound import BoundComputeCall, BoundPlan
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.state import PayloadRef, StateValue
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
    ExperimentPreviewStateTarget,
)


def build_experiment_preview(plan: BoundPlan) -> ExperimentPreview:
    """Project one accepted plan without rebuilding any compiler graph."""

    coordinate_ids = _coordinate_ids(plan)
    payloads = _preview_payloads(plan)
    compute_steps = tuple(
        _preview_compute_step(point.point_index, call)
        for point in plan.points
        for call in point.compute
    )
    state_fields = tuple(
        ExperimentPreviewStateField(
            point_index=point.point_index,
            resource_id=state.resource_id,
            capability_id=state.capability_id,
            field_path=field.field_path,
            value=field.value.root,
            channel_bindings=_preview_channel_bindings(field.channel_bindings),
        )
        for point in plan.points
        for state in point.desired_state
        for field in state.fields
    )
    dataset_dimensions = (
        {
            dimension.id: dimension.size
            for dimension in plan.expected_dataset_schema.dimensions
            if dimension.size is not None
        }
        if plan.expected_dataset_schema is not None
        else {}
    )
    primary_observables = (
        tuple(plan.expected_dataset_schema.primary_observables)
        if plan.expected_dataset_schema is not None
        else tuple(record.id for record in plan.records if record.kind == "observable")
    )
    return ExperimentPreview(
        experiment_id=plan.experiment_id,
        experiment_kind=plan.experiment_kind,
        point_count=plan.point_count,
        schema=plan.expected_dataset_schema,
        coordinate_ids=coordinate_ids,
        points=tuple(
            ExperimentPreviewPoint(
                point_index=point.point_index,
                point_uid=point.point_uid,
                coordinates={
                    coordinate_id: point.coordinates[coordinate_id]
                    for coordinate_id in coordinate_ids
                },
            )
            for point in plan.points
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
                dims=record.dims,
                shape=record.shape,
            )
            for record in plan.records
        ),
        state_changes=tuple(
            ExperimentPreviewStateChange(
                point_index=change.point_index,
                resource=change.resource,
                capability_id=change.capability_id,
                field_path=change.field_path,
                before=_preview_state_value(change.before),
                after=_preview_state_value(change.after),
            )
            for change in plan.state_changes
        ),
        routes=tuple(
            ExperimentPreviewRoute(
                port_id=intent.port_id,
                capabilities=intent.capabilities,
                entity_expr_count=len(intent.entity_exprs),
                fixed_resource=intent.resource_id,
                resolved=tuple(
                    ExperimentPreviewResolvedRoute(
                        point_index=point.point_index,
                        port_id=route.port_id,
                        resource_id=route.resource_id,
                        entity_ids=route.entity_ids,
                        product_axis_order=route.product_axis_order,
                        channel_bindings=_preview_channel_bindings(
                            route.channel_bindings
                        ),
                    )
                    for point in plan.points
                    for route in point.routes
                    if route.port_id == intent.port_id
                ),
            )
            for intent in plan.route_intents
        ),
        state_fields=state_fields,
        payloads=payloads,
        compute_steps=compute_steps,
        runtime=ExperimentPreviewRuntimeSummary(
            route_count=len(plan.route_intents),
            state_field_count=len(state_fields),
            compute_node_count=len(
                {call.node_id for point in plan.points for call in point.compute}
            ),
            compute_step_count=len(compute_steps),
            payload_count=len(payloads),
        ),
        dataset_dimensions=dataset_dimensions,
        primary_observables=primary_observables,
    )


def _coordinate_ids(plan: BoundPlan) -> tuple[str, ...]:
    if plan.expected_dataset_schema is not None:
        return tuple(plan.expected_dataset_schema.primary_coordinates)
    return plan.point_coordinate_ids


def _preview_compute_step(
    point_index: int,
    call: BoundComputeCall,
) -> ExperimentPreviewComputeStep:
    return ExperimentPreviewComputeStep(
        point_index=point_index,
        node_id=call.node_id.qualified_name,
        payload_id=call.payload_id,
        schema_id=call.payload_schema_id,
        dependencies=dict(call.dependencies),
    )


def _preview_payloads(plan: BoundPlan) -> tuple[ExperimentPreviewPayload, ...]:
    calls_by_payload_id = {
        call.payload_id: call
        for point in plan.points
        for call in point.compute
        if call.payload_id is not None
    }
    fields_by_node: dict[tuple[str, str], set[tuple[str, str]]] = {}
    dependencies_by_node: dict[tuple[str, str], Mapping[str, tuple[str, ...]]] = {}
    for point in plan.points:
        for state in point.desired_state:
            for field in state.fields:
                value = field.value.root
                if not isinstance(value, PayloadRef):
                    continue
                call = calls_by_payload_id.get(value.payload_id)
                if call is None or call.payload_schema_id is None:
                    continue
                key = (call.node_id.qualified_name, call.payload_schema_id)
                fields_by_node.setdefault(key, set()).add(
                    (state.capability_id, field.field_path)
                )
                dependencies_by_node.setdefault(key, call.dependencies)
    return tuple(
        ExperimentPreviewPayload(
            node_id=node_id,
            schema_id=schema_id,
            state_fields=tuple(
                ExperimentPreviewStateTarget(
                    capability_id=capability_id,
                    field_path=field_path,
                )
                for capability_id, field_path in sorted(fields)
            ),
            dependencies=dict(dependencies_by_node.get((node_id, schema_id), {})),
        )
        for (node_id, schema_id), fields in sorted(fields_by_node.items())
    )


def _preview_state_value(value: object) -> object:
    return value.root if isinstance(value, StateValue) else value


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


__all__ = ["build_experiment_preview"]
