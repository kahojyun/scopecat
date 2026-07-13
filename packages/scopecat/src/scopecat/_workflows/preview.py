"""Pure projections from the config-bound plan into user-visible summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat._compiler.bound import BoundComputeCall, BoundPlan, BoundRecord
from scopecat._compiler.product_realizations import SelectedLocalProductRealization
from scopecat._resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.run_plan import RunPlanRecord
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
            resource_id=state.resource_id.value,
            resource_port_id=(
                field.resource_port_id.qualified_name
                if field.resource_port_id is not None
                else None
            ),
            capability_id=state.capability_id,
            field_path=field.field_path,
            value=field.value.root,
            entity_ids=field.entity_ids,
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
    selected = plan.local_product_realizations
    realizations_by_use = (
        {realization.product_use_id: realization for realization in selected.entries}
        if selected is not None
        else {}
    )
    primary_observables = (
        tuple(plan.expected_dataset_schema.primary_observables)
        if plan.expected_dataset_schema is not None
        else tuple(
            record.id
            for record in plan.records
            if record.kind == "observable"
            and record.product_use_id in realizations_by_use
        )
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
                point_uid=point.logical_id.value,
                coordinates={
                    coordinate_id: point.coordinates[coordinate_id]
                    for coordinate_id in coordinate_ids
                },
            )
            for point in plan.points
        ),
        records=tuple(
            _preview_record(record, realizations_by_use[record.product_use_id])
            for record in plan.records
            if record.product_use_id in realizations_by_use
        ),
        state_changes=tuple(
            ExperimentPreviewStateChange(
                point_index=change.point_index,
                resource_id=change.resource_id.value,
                resource_port_id=(
                    change.resource_port_id.qualified_name
                    if change.resource_port_id is not None
                    else None
                ),
                capability_id=change.capability_id,
                field_path=change.field_path,
                before=_preview_state_value(change.before),
                after=_preview_state_value(change.after),
                entity_ids=change.entity_ids,
                channel_bindings=_preview_channel_bindings(change.channel_bindings),
            )
            for change in plan.state_changes
        ),
        routes=tuple(
            ExperimentPreviewRoute(
                port_id=intent.port_id.qualified_name,
                capabilities=intent.capabilities,
                entity_expr_count=len(intent.entity_uses),
                fixed_resource_id=(
                    intent.fixed_resource_id.value
                    if intent.fixed_resource_id is not None
                    else None
                ),
                resolved=tuple(
                    ExperimentPreviewResolvedRoute(
                        point_index=point.point_index,
                        port_id=route.port_id.qualified_name,
                        resource_id=route.resource_id.value,
                        resource_kind=route.resource_kind,
                        entity_ids=route.entity_ids,
                        served_entity_ids=route.served_entity_ids,
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
            compute_operation_count=len(
                {call.operation_id for point in plan.points for call in point.compute}
            ),
            compute_step_count=len(compute_steps),
            payload_count=len(payloads),
        ),
        dataset_dimensions=dataset_dimensions,
        primary_observables=primary_observables,
    )


def build_domain_experiment_preview(plan: RunPlanRecord) -> ExperimentPreview:
    """Project domain accepted-plan evidence into the common user preview."""

    return ExperimentPreview(
        experiment_id=plan.experiment_id,
        experiment_kind=plan.experiment_kind,
        point_count=plan.point_count,
        schema=plan.expected_dataset_schema,
        coordinate_ids=tuple(plan.coordinate_ids),
        points=tuple(
            ExperimentPreviewPoint(
                point_index=point.point_index,
                point_uid=point.point_uid,
                coordinates=dict(point.coordinates),
            )
            for point in plan.points
        ),
        records=tuple(
            ExperimentPreviewRecord(
                id=record.id,
                kind=record.kind,
                producer_kind=record.producer_kind,
                resource_port_id=record.resource_port_id,
                physical_resource_id=record.physical_resource_id,
                capability=record.capability,
                unit=record.unit,
                dtype=record.dtype,
                dims=tuple(record.dims),
                shape=tuple(record.shape),
            )
            for record in plan.records
        ),
        state_changes=(),
        routes=(),
        state_fields=(),
        payloads=(),
        compute_steps=(),
        runtime=ExperimentPreviewRuntimeSummary(
            route_count=0,
            state_field_count=0,
            compute_operation_count=0,
            compute_step_count=0,
            payload_count=0,
        ),
        dataset_dimensions=dict(plan.dataset_dimensions),
        primary_observables=tuple(plan.primary_observables),
    )


def _preview_record(
    record: BoundRecord,
    realization: SelectedLocalProductRealization,
) -> ExperimentPreviewRecord:
    producer = realization.producer
    return ExperimentPreviewRecord(
        id=record.id,
        kind=record.kind,
        producer_kind="instrument",
        resource_port_id=(
            producer.resource_target.qualified_name
            if isinstance(producer.resource_target, LogicalResourcePortId)
            else None
        ),
        physical_resource_id=(
            producer.resource_target.value
            if isinstance(producer.resource_target, PhysicalResourceId)
            else (
                realization.implicit_resource_id.value
                if realization.implicit_resource_id is not None
                else None
            )
        ),
        capability=producer.capability,
        unit=record.unit,
        dtype=record.dtype,
        dims=record.dims,
        shape=record.shape,
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
        semantic_operation_id=call.operation_id.qualified_name,
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
    fields_by_node: dict[
        tuple[str, str],
        set[tuple[str, str, str, str | None, tuple[str, ...]]],
    ] = {}
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
                key = (call.operation_id.qualified_name, call.payload_schema_id)
                fields_by_node.setdefault(key, set()).add(
                    (
                        state.resource_id.value,
                        state.capability_id,
                        field.field_path,
                        (
                            field.resource_port_id.qualified_name
                            if field.resource_port_id is not None
                            else None
                        ),
                        field.entity_ids,
                    )
                )
                dependencies_by_node.setdefault(key, call.dependencies)
    return tuple(
        ExperimentPreviewPayload(
            semantic_operation_id=semantic_operation_id,
            schema_id=schema_id,
            state_fields=tuple(
                ExperimentPreviewStateTarget(
                    resource_id=resource_id,
                    capability_id=capability_id,
                    field_path=field_path,
                    resource_port_id=resource_port_id,
                    entity_ids=entity_ids,
                )
                for (
                    resource_id,
                    capability_id,
                    field_path,
                    resource_port_id,
                    entity_ids,
                ) in sorted(fields, key=repr)
            ),
            dependencies=dict(
                dependencies_by_node.get((semantic_operation_id, schema_id), {})
            ),
        )
        for (semantic_operation_id, schema_id), fields in sorted(fields_by_node.items())
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


__all__ = ["build_domain_experiment_preview", "build_experiment_preview"]
