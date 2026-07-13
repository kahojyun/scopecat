"""Durable accepted-plan projection from the config-bound compiler IR."""

from __future__ import annotations

from typing import cast

from scopecat._compiler.bound import BoundPlan, BoundRecord
from scopecat._compiler.product_realizations import SelectedLocalProductRealization
from scopecat._resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.run_plan import (
    RunPlanChannelBinding,
    RunPlanDeferredValue,
    RunPlanOutput,
    RunPlanPoint,
    RunPlanRecord,
    RunPlanResolvedRoute,
    RunPlanRoute,
    RunPlanStateChange,
    RunPlanValue,
)
from scopecat.models.state import PayloadRef, StateValue


def build_run_plan_record(plan: BoundPlan) -> RunPlanRecord:
    """Project transient compiler output into durable accepted-plan evidence."""

    if not plan.valid:
        msg = "durable run plans require a valid bound plan"
        raise ValueError(msg)

    coordinate_ids = _coordinate_ids(plan)
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
        list(plan.expected_dataset_schema.primary_observables)
        if plan.expected_dataset_schema is not None
        else [record.id for record in plan.records if record.kind == "observable"]
    )
    selected = plan.local_product_realizations
    if selected is None:
        msg = "durable run plans require selected local product realizations"
        raise ValueError(msg)
    realizations_by_use = {
        realization.product_use_id: realization for realization in selected.entries
    }
    return RunPlanRecord(
        experiment_id=plan.experiment_id,
        experiment_kind=plan.experiment_kind,
        point_count=plan.point_count,
        expected_dataset_schema=plan.expected_dataset_schema,
        coordinate_ids=list(coordinate_ids),
        points=[
            RunPlanPoint(
                point_index=point.point_index,
                point_uid=point.logical_id.value,
                coordinates={
                    coordinate_id: point.coordinates[coordinate_id]
                    for coordinate_id in coordinate_ids
                },
            )
            for point in plan.points
        ],
        records=[
            _run_plan_output(record, realizations_by_use[record.product_use_id])
            for record in plan.records
        ],
        state_changes=[
            RunPlanStateChange(
                point_index=change.point_index,
                resource_id=change.resource_id.value,
                resource_port_id=(
                    change.resource_port_id.qualified_name
                    if change.resource_port_id is not None
                    else None
                ),
                capability_id=change.capability_id,
                field_path=change.field_path,
                before=cast("RunPlanValue", _run_plan_state_value(change.before)),
                after=cast("RunPlanValue", _run_plan_state_value(change.after)),
                entity_ids=list(change.entity_ids),
                channel_bindings=[
                    _run_plan_channel_binding(binding)
                    for binding in change.channel_bindings
                ],
            )
            for change in plan.state_changes
        ],
        routes=[
            RunPlanRoute(
                port_id=intent.port_id.qualified_name,
                capabilities=list(intent.capabilities),
                entity_expr_count=len(intent.entity_uses),
                fixed_resource_id=(
                    intent.fixed_resource_id.value
                    if intent.fixed_resource_id is not None
                    else None
                ),
                resolved=[
                    RunPlanResolvedRoute(
                        point_index=point.point_index,
                        port_id=route.port_id.qualified_name,
                        resource_id=route.resource_id.value,
                        resource_kind=route.resource_kind,
                        entity_ids=list(route.entity_ids),
                        served_entity_ids=list(route.served_entity_ids),
                        product_axis_order=list(route.product_axis_order),
                        channel_bindings=[
                            _run_plan_channel_binding(binding)
                            for binding in route.channel_bindings
                        ],
                    )
                    for point in plan.points
                    for route in point.routes
                    if route.port_id == intent.port_id
                ],
            )
            for intent in plan.route_intents
        ],
        dataset_dimensions=dataset_dimensions,
        primary_observables=primary_observables,
    )


def _run_plan_output(
    record: BoundRecord,
    realization: SelectedLocalProductRealization,
) -> RunPlanOutput:
    producer = realization.producer
    return RunPlanOutput(
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
        dims=list(record.dims),
        shape=list(record.shape),
    )


def _coordinate_ids(plan: BoundPlan) -> tuple[str, ...]:
    if plan.expected_dataset_schema is not None:
        return tuple(plan.expected_dataset_schema.primary_coordinates)
    return plan.point_coordinate_ids


def _run_plan_state_value(value: object) -> object:
    selected = value.root if isinstance(value, StateValue) else value
    if isinstance(selected, PayloadRef):
        return RunPlanDeferredValue()
    return selected


def _run_plan_channel_binding(
    binding: RoutingChannelBinding,
) -> RunPlanChannelBinding:
    return RunPlanChannelBinding(
        entity_id=binding.entity_id,
        channel_id=binding.channel_id,
        line_id=binding.line_id,
        capability=binding.capability,
        group_ids=list(binding.group_ids),
    )


__all__ = ["build_run_plan_record"]
