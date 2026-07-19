from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import materialize_linked_points
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.typed.program import CoreProgram
from scopecat.execution.local.program import (
    ApplyStateOperation,
    StateTarget,
)
from scopecat.measurements._bridge import project_measurement_catalog
from scopecat.measurements.projection import (
    MeasurementProjection,
    select_measurement_projection,
)
from scopecat.records.config import ConfigProfileSnapshot, RoutingResource
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    MaterializedLocalEffects,
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.typed_program import link_program


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


def materialized_effects_contract(
    experiment: CoreProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> MaterializedLocalEffects:
    environment = replace(
        validate_config_environment(config or load_config()),
        parameters=parameters,
    )
    return materialize_local_execution(link_program(experiment, environment))


def measurement_projection_contract(
    experiment: CoreProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> MeasurementProjection:
    environment = replace(
        validate_config_environment(config or load_config()),
        parameters=parameters,
    )
    linked_points = materialize_linked_points(link_program(experiment, environment))
    return select_measurement_projection(
        project_measurement_catalog(linked_points),
        linked_points.linked_plan.record_uses,
    )


def materialized_state_fields(
    plan: MaterializedLocalEffects,
) -> tuple[tuple[int, ApplyStateOperation, StateTarget], ...]:
    """Flatten bound state for focused assertions without another projection."""

    return tuple(
        (point.point_index, operation, target)
        for point in plan.points
        for operation in operations_of_type(point, ApplyStateOperation)
        for target in operation.targets
    )
