"""Durable accepted-plan projection from the config-bound compiler IR."""

from __future__ import annotations

from typing import cast

from scopecat._compiler.bound import BoundPlan
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
    return RunPlanRecord(
        experiment_id=plan.experiment_id,
        experiment_kind=plan.experiment_kind,
        point_count=plan.point_count,
        expected_dataset_schema=plan.expected_dataset_schema,
        coordinate_ids=list(coordinate_ids),
        points=[
            RunPlanPoint(
                point_index=point.point_index,
                point_uid=point.point_uid,
                coordinates={
                    coordinate_id: point.coordinates[coordinate_id]
                    for coordinate_id in coordinate_ids
                },
            )
            for point in plan.points
        ],
        records=[
            RunPlanOutput(
                id=record.id,
                kind=record.kind,
                source=record.source,
                resource=record.resource,
                capability=record.capability,
                unit=record.unit,
                dtype=record.dtype,
                dims=list(record.dims),
                shape=list(record.shape),
            )
            for record in plan.records
        ],
        state_changes=[
            RunPlanStateChange(
                point_index=change.point_index,
                resource=change.resource,
                field=change.field,
                before=cast("RunPlanValue", _run_plan_state_value(change.before)),
                after=cast("RunPlanValue", _run_plan_state_value(change.after)),
            )
            for change in plan.state_changes
        ],
        routes=[
            RunPlanRoute(
                port_id=intent.port_id,
                capabilities=list(intent.capabilities),
                entity_expr_count=len(intent.entity_exprs),
                fixed_resource=intent.resource_id,
                resolved=[
                    RunPlanResolvedRoute(
                        point_index=point.point_index,
                        port_id=route.port_id,
                        resource_id=route.resource_id,
                        entity_ids=list(route.entity_ids),
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
