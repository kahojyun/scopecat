"""Validate complete configuration profiles."""

from __future__ import annotations

from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.config import ConfigProfileSnapshot


def _problem(
    code: str,
    message: str,
    path: tuple[str | int, ...],
) -> Problem:
    return problem(
        f"configuration.{code}",
        message,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config_profile", *path),
    )


def _routing_binding_problems(
    config: ConfigProfileSnapshot,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    path = ("system", "routing", "bindings")
    instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    entity_ids = {entity.id for entity in config.topology.entities}

    for binding in config.routing.bindings:
        if binding.instrument_id not in instrument_ids:
            problems.append(
                _problem(
                    "unknown_routing_binding_instrument",
                    "routing binding references unknown instrument "
                    f"{binding.instrument_id}",
                    path,
                )
            )
        if binding.entity_id is not None and binding.entity_id not in entity_ids:
            problems.append(
                _problem(
                    "unknown_routing_binding_entity",
                    f"routing binding references unknown entity {binding.entity_id}",
                    path,
                )
            )
        if binding.channel_id is None:
            continue
        if binding.entity_id is None:
            problems.append(
                _problem(
                    "routing_binding_channel_without_entity",
                    f"routing binding for channel {binding.channel_id} must "
                    "declare an entity",
                    path,
                )
            )
    return tuple(problems)


def validate_config_profile(
    config: ConfigProfileSnapshot,
    *,
    include_parameter_values: bool = True,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []

    entity_ids = {entity.id for entity in config.topology.entities}
    if (
        config.primary_entity_id
        and entity_ids
        and config.primary_entity_id not in entity_ids
    ):
        problems.append(
            _problem(
                "unknown_primary_entity",
                "primary_entity_id references an unknown entity "
                f"{config.primary_entity_id}",
                ("system", "primary_entity_id"),
            )
        )

    problems.extend(_routing_binding_problems(config))

    if include_parameter_values:
        problems.extend(resolve_config_parameters(config).problems)

    return tuple(problems)
