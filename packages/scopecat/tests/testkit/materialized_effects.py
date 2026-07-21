from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import LinkedPointMaterializer
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
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
)
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
)
from tests.testkit.typed_program import link_program


def config_with_physical_resources(
    resources: Mapping[str, Sequence[str]],
) -> ConfigProfileSnapshot:
    """Extend the test config with explicit instrument capability bindings."""

    config = load_config()
    existing_instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seed_instrument = config.instrument_registry.instruments[0]
    routing_bindings = list(config.routing.bindings)
    binding_keys = {
        (binding.instrument_id, binding.capability) for binding in routing_bindings
    }
    for resource_id, capabilities in resources.items():
        for capability in dict.fromkeys(capabilities):
            key = (resource_id, capability)
            if key in binding_keys:
                continue
            routing_bindings.append(
                RoutingEndpointBinding(
                    instrument_id=resource_id,
                    capability=capability,
                )
            )
            binding_keys.add(key)

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
    linked_points = LinkedPointMaterializer(
        link_program(experiment, environment)
    ).materialize()
    return select_measurement_projection(
        project_measurement_catalog(linked_points),
        linked_points.linked_plan.program.record_uses,
    )


def materialized_state_fields(
    plan: LocalEffectInspection,
) -> tuple[tuple[int, ApplyStateOperation, StateTarget], ...]:
    """Flatten exact state coverage for focused assertions."""

    return tuple(
        (point_index, operation, target)
        for effect in plan.effects
        if isinstance(operation := effect.operation, ApplyStateOperation)
        for point_index in effect.point_indices
        for target in operation.targets
    )
