from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from scopecat.compiler.linking.linked import link_program, materialize_linked_points
from scopecat.compiler.measurement_projection import project_measurement_catalog
from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.typed.program import CoreProgram
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import (
    ApplyStateOperation,
    StateTarget,
)
from scopecat.measurements.projection import (
    MeasurementProjection,
    select_measurement_projection,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
)
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
)


def config_with_physical_resources(
    resources: Mapping[str, Sequence[str]],
) -> ConfigProfileSnapshot:
    """Extend the test config with explicit instrument interface bindings."""

    config = load_config()
    existing_instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seed_instrument = config.instrument_registry.instruments[0]
    routing_bindings = list(config.routing.bindings)
    binding_keys = {
        (binding.instrument_id, binding.interface_id) for binding in routing_bindings
    }
    for resource_id, interfaces in resources.items():
        for interface_id in dict.fromkeys(interfaces):
            key = (resource_id, interface_id)
            if key in binding_keys:
                continue
            routing_bindings.append(
                RoutingEndpointBinding(
                    instrument_id=resource_id,
                    interface_id=interface_id,
                )
            )
            binding_keys.add(key)

    instruments = list(config.instrument_registry.instruments)
    instruments.extend(
        seed_instrument.model_copy(
            update={"id": resource_id, "exclusivity_key": resource_id}
        )
        for resource_id in resources
        if resource_id not in existing_instrument_ids
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={"instruments": instruments}
            ),
            "routing": config.routing.model_copy(update={"bindings": routing_bindings}),
        }
    )
    return config.model_copy(update={"system": system})


def materialized_effects_contract(
    experiment: CoreProgram,
    parameters: ParameterRelationData,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> LocalEffectInspection:
    environment = replace(
        build_config_environment(config or load_config()),
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
        build_config_environment(config or load_config()),
        parameters=parameters,
    )
    linked_points = materialize_linked_points(link_program(experiment, environment))
    return select_measurement_projection(
        project_measurement_catalog(linked_points),
        linked_points.linked_plan.program.record_uses,
    )


def materialized_state_properties(
    plan: LocalEffectInspection,
) -> tuple[tuple[int, ApplyStateOperation, StateTarget], ...]:
    """Flatten materialized state-property targets for focused assertions."""

    return tuple(
        (effect.point_index, operation, target)
        for effect in plan.effects
        if isinstance(operation := effect.operation, ApplyStateOperation)
        for target in operation.targets
    )
