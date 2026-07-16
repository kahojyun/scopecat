from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.bound import (
    BoundPlan,
    BoundResourceState,
    BoundStateField,
)
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.relations.backend import ParameterRelationData
from scopecat.compiler.typed.program import TypedProgram
from scopecat.kernel.problems import Problem
from scopecat.kernel.state import StateValue
from scopecat.records.config import ConfigProfileSnapshot, RoutingResource
from tests.testkit.authoring import load_config


def config_with_physical_resources(
    resources: Mapping[str, Sequence[str]],
) -> ConfigProfileSnapshot:
    """Extend the test config with explicit physical-resource contracts."""

    config = load_config()
    existing_resource_ids = {resource.id for resource in config.routing.resources}
    existing_instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seed_instrument = config.instrument_registry.instruments[0]
    routing_resources: list[RoutingResource] = list(config.routing.resources)
    for resource_id, capabilities in resources.items():
        if resource_id in existing_resource_ids:
            routing_resources = [
                resource.model_copy(
                    update={
                        "capabilities": list(
                            dict.fromkeys((*resource.capabilities, *capabilities))
                        )
                    }
                )
                if resource.id == resource_id
                else resource
                for resource in routing_resources
            ]
        else:
            routing_resources.append(
                RoutingResource(
                    id=resource_id,
                    capabilities=list(capabilities),
                )
            )
        existing_resource_ids.add(resource_id)

    instruments = list(config.instrument_registry.instruments)
    instruments.extend(
        seed_instrument.model_copy(update={"id": resource_id})
        for resource_id in resources
        if resource_id not in existing_instrument_ids
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={"instruments": instruments}
            ),
            "routing": config.routing.model_copy(
                update={"resources": routing_resources}
            ),
        }
    )
    return config.model_copy(update={"system": system})


def bound_plan_contract(
    experiment: TypedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> BoundPlan:
    plan, problems = bound_plan_result(
        experiment,
        parameters,
        config=config,
    )
    assert problems == ()
    return plan


def bound_plan_result(
    experiment: TypedProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> tuple[BoundPlan, tuple[Problem, ...]]:
    environment = replace(
        validate_config_environment(config or load_config()),
        parameters=parameters,
    )
    plan = materialize_local_plan(link_program(experiment, environment))
    return plan, plan.problems


def bound_state_fields(
    plan: BoundPlan,
) -> tuple[tuple[int, BoundResourceState, BoundStateField], ...]:
    """Flatten bound state for focused assertions without another projection."""

    return tuple(
        (point.point_index, state, field)
        for point in plan.points
        for state in point.desired_state
        for field in state.fields
    )


def bound_coordinate_ids(plan: BoundPlan) -> tuple[str, ...]:
    schema = plan.expected_dataset_schema
    if schema is not None:
        return tuple(schema.primary_coordinates)
    return plan.point_coordinate_ids


def bound_primary_observables(plan: BoundPlan) -> tuple[str, ...]:
    schema = plan.expected_dataset_schema
    if schema is not None:
        return tuple(schema.primary_observables)
    return tuple(record.id for record in plan.records if record.kind == "observable")


def bound_dataset_dimensions(plan: BoundPlan) -> dict[str, int]:
    schema = plan.expected_dataset_schema
    dimensions = (
        {
            dimension.id: dimension.size
            for dimension in schema.dimensions
            if dimension.size is not None
        }
        if schema is not None
        else {}
    )
    if (
        schema is not None
        and any(dimension.id == "point" for dimension in schema.dimensions)
    ) or any("point" in record.dims for record in plan.records):
        dimensions["point"] = len(plan.points)
    return dimensions


def state_literal(value: object) -> object:
    return value.root if isinstance(value, StateValue) else value
