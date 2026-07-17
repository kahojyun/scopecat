"""Structured configuration checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.config import (
    Channel,
    ConfigProfileSnapshot,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingResource,
)


@dataclass(slots=True)
class _RoutingValidationContext:
    resources: dict[str, RoutingResource]
    entity_ids: set[str]
    channel_ids: set[str]
    line_ids: set[str]
    group_ids: set[str]
    channels_by_id: dict[str, Channel]
    target_topologies: dict[
        tuple[str, str, str], tuple[str | None, tuple[str, ...]]
    ] = field(default_factory=dict)


def _problem(
    code: str,
    message: str,
    path: tuple[str | int, ...],
) -> Problem:
    return blocking_problem(
        f"configuration.{code}",
        message,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config_profile", *path),
    )


def _routing_binding_problems(
    edge: RoutingEdge,
    binding: RoutingChannelBinding,
    resource: RoutingResource | None,
    context: _RoutingValidationContext,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    path = ("system", "routing", "edges")
    if binding.entity_id not in context.entity_ids:
        problems.append(
            _problem(
                "unknown_routing_binding_entity",
                f"routing edge {edge.id} binding references unknown entity "
                f"{binding.entity_id}",
                path,
            )
        )
    elif edge.entity_ids and binding.entity_id not in edge.entity_ids:
        problems.append(
            _problem(
                "routing_binding_edge_entity_mismatch",
                f"routing edge {edge.id} binding references entity "
                f"{binding.entity_id}, but the edge does not list it",
                path,
            )
        )
    elif (
        resource is not None
        and resource.served_entities
        and binding.entity_id not in resource.served_entities
    ):
        problems.append(
            _problem(
                "routing_binding_resource_entity_mismatch",
                f"routing edge {edge.id} binding references entity "
                f"{binding.entity_id}, but resource {edge.resource_id} "
                "does not serve it",
                path,
            )
        )
    if binding.capability is not None:
        if edge.capabilities and binding.capability not in edge.capabilities:
            problems.append(
                _problem(
                    "routing_binding_edge_capability_mismatch",
                    f"routing edge {edge.id} binding references capability "
                    f"{binding.capability}, but the edge does not list it",
                    path,
                )
            )
        if (
            resource is not None
            and resource.capabilities
            and binding.capability not in resource.capabilities
        ):
            problems.append(
                _problem(
                    "routing_binding_resource_capability_mismatch",
                    f"routing edge {edge.id} binding references capability "
                    f"{binding.capability}, but resource {edge.resource_id} "
                    "does not declare it",
                    path,
                )
            )
    if binding.channel_id not in context.channel_ids:
        problems.append(
            _problem(
                "unknown_routing_binding_channel",
                f"routing edge {edge.id} binding references unknown channel "
                f"{binding.channel_id}",
                path,
            )
        )
    else:
        channel = context.channels_by_id[binding.channel_id]
        target = (edge.resource_id, binding.entity_id, binding.channel_id)
        topology = (
            binding.line_id or channel.line_id,
            tuple(sorted(binding.group_ids or channel.group_ids)),
        )
        previous_topology = context.target_topologies.setdefault(target, topology)
        if previous_topology != topology:
            problems.append(
                _problem(
                    "routing_binding_topology_conflict",
                    f"routing bindings for resource {edge.resource_id}, "
                    f"entity {binding.entity_id}, and channel "
                    f"{binding.channel_id} disagree on physical topology",
                    path,
                )
            )
        if edge.channels and binding.channel_id not in edge.channels:
            problems.append(
                _problem(
                    "routing_binding_edge_channel_mismatch",
                    f"routing edge {edge.id} binding references channel "
                    f"{binding.channel_id}, but the edge does not list it",
                    path,
                )
            )
        if (
            resource is not None
            and resource.channels
            and binding.channel_id not in resource.channels
        ):
            problems.append(
                _problem(
                    "routing_binding_resource_channel_mismatch",
                    f"routing edge {edge.id} binding references channel "
                    f"{binding.channel_id}, but resource {edge.resource_id} "
                    "does not list it",
                    path,
                )
            )
        if (
            binding.line_id is not None
            and channel.line_id is not None
            and binding.line_id != channel.line_id
        ):
            problems.append(
                _problem(
                    "routing_binding_line_mismatch",
                    f"routing edge {edge.id} binding line {binding.line_id} "
                    f"does not match topology channel {binding.channel_id} "
                    f"line {channel.line_id}",
                    path,
                )
            )
        if (
            binding.group_ids
            and channel.group_ids
            and set(binding.group_ids) != set(channel.group_ids)
        ):
            problems.append(
                _problem(
                    "routing_binding_group_mismatch",
                    f"routing edge {edge.id} binding groups "
                    f"{sorted(binding.group_ids)} do not match topology channel "
                    f"{binding.channel_id} groups {sorted(channel.group_ids)}",
                    path,
                )
            )
    if binding.line_id is not None and binding.line_id not in context.line_ids:
        problems.append(
            _problem(
                "unknown_routing_binding_line",
                f"routing edge {edge.id} binding references unknown line "
                f"{binding.line_id}",
                path,
            )
        )
    for group_id in binding.group_ids:
        if group_id not in context.group_ids:
            problems.append(
                _problem(
                    "unknown_routing_binding_group",
                    f"routing edge {edge.id} binding references unknown group "
                    f"{group_id}",
                    path,
                )
            )
    return tuple(problems)


def _routing_edge_problems(
    config: ConfigProfileSnapshot,
    context: _RoutingValidationContext,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    path = ("system", "routing", "edges")
    for edge in config.routing.edges:
        resource = context.resources.get(edge.resource_id)
        if resource is None:
            problems.append(
                _problem(
                    "unknown_routing_edge_resource",
                    f"routing edge {edge.id} references unknown resource "
                    f"{edge.resource_id}",
                    path,
                )
            )
        for entity_id in edge.entity_ids:
            if entity_id not in context.entity_ids:
                problems.append(
                    _problem(
                        "unknown_routing_edge_entity",
                        f"routing edge {edge.id} references unknown entity {entity_id}",
                        path,
                    )
                )
            elif (
                resource is not None
                and resource.served_entities
                and entity_id not in resource.served_entities
            ):
                problems.append(
                    _problem(
                        "routing_edge_resource_entity_mismatch",
                        f"routing edge {edge.id} references entity {entity_id}, "
                        f"but resource {edge.resource_id} does not serve it",
                        path,
                    )
                )
        for channel_id in edge.channels:
            if channel_id not in context.channel_ids:
                problems.append(
                    _problem(
                        "unknown_routing_edge_channel",
                        f"routing edge {edge.id} references unknown channel "
                        f"{channel_id}",
                        path,
                    )
                )
            elif (
                resource is not None
                and resource.channels
                and channel_id not in resource.channels
            ):
                problems.append(
                    _problem(
                        "routing_edge_resource_channel_mismatch",
                        f"routing edge {edge.id} references channel {channel_id}, "
                        f"but resource {edge.resource_id} does not list it",
                        path,
                    )
                )
        for binding in edge.bindings:
            problems.extend(_routing_binding_problems(edge, binding, resource, context))
        if resource is not None:
            for capability in edge.capabilities:
                if capability not in resource.capabilities:
                    problems.append(
                        _problem(
                            "unknown_routing_edge_capability",
                            f"routing edge {edge.id} references capability "
                            f"{capability} not declared by resource "
                            f"{edge.resource_id}",
                            path,
                        )
                    )
    return tuple(problems)


def _topology_problems(config: ConfigProfileSnapshot) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    entity_ids = {entity.id for entity in config.topology.entities}
    device_ids = {device.id for device in config.topology.devices}
    line_ids = {line.id for line in config.topology.lines}
    channel_ids = {channel.id for channel in config.topology.channels}
    group_ids = {group.id for group in config.topology.groups}
    lines_by_id = {line.id: line for line in config.topology.lines}
    channels_by_id = {channel.id: channel for channel in config.topology.channels}
    groups_by_id = {group.id: group for group in config.topology.groups}

    for channel in config.topology.channels:
        if channel.device_id is not None and channel.device_id not in device_ids:
            problems.append(
                _problem(
                    "unknown_channel_device",
                    f"channel {channel.id} references unknown device "
                    f"{channel.device_id}",
                    ("topology", "channels"),
                )
            )
        if channel.line_id is not None and channel.line_id not in line_ids:
            problems.append(
                _problem(
                    "unknown_channel_line",
                    f"channel {channel.id} references unknown line {channel.line_id}",
                    ("topology", "channels"),
                )
            )
        elif channel.line_id is not None and channel.device_id is not None:
            line = lines_by_id[channel.line_id]
            if line.endpoints and channel.device_id not in line.endpoints:
                problems.append(
                    _problem(
                        "topology_channel_line_endpoint_mismatch",
                        f"channel {channel.id} references line {channel.line_id} "
                        f"and device {channel.device_id}, but the line endpoints "
                        "do not include that device",
                        ("topology", "channels"),
                    )
                )
        for group_id in channel.group_ids:
            if group_id not in group_ids:
                problems.append(
                    _problem(
                        "unknown_channel_group",
                        f"channel {channel.id} references unknown group {group_id}",
                        ("topology", "channels"),
                    )
                )
            else:
                group = groups_by_id[group_id]
                if (
                    group.members
                    and channel.id not in group.members
                    and (
                        channel.line_id is None or channel.line_id not in group.members
                    )
                ):
                    problems.append(
                        _problem(
                            "topology_channel_group_mismatch",
                            f"channel {channel.id} references group {group_id}, "
                            "but that group does not list the channel or its line",
                            ("topology", "channels"),
                        )
                    )

    for line in config.topology.lines:
        for endpoint in line.endpoints:
            if endpoint not in entity_ids and endpoint not in device_ids:
                problems.append(
                    _problem(
                        "unknown_line_endpoint",
                        f"line {line.id} references unknown endpoint {endpoint}",
                        ("topology", "lines"),
                    )
                )

    for group in config.topology.groups:
        for member in group.members:
            if member not in channel_ids and member not in line_ids:
                problems.append(
                    _problem(
                        "unknown_group_member",
                        f"group {group.id} references unknown member {member}",
                        ("topology", "groups"),
                    )
                )
            elif member in channel_ids:
                channel = channels_by_id[member]
                if channel.group_ids and group.id not in channel.group_ids:
                    problems.append(
                        _problem(
                            "topology_group_member_mismatch",
                            f"group {group.id} lists channel {member}, but that "
                            "channel does not reference the group",
                            ("topology", "groups"),
                        )
                    )
            else:
                for channel in config.topology.channels:
                    if channel.line_id != member:
                        continue
                    if channel.group_ids and group.id not in channel.group_ids:
                        problems.append(
                            _problem(
                                "topology_group_member_mismatch",
                                f"group {group.id} lists line {member}, but channel "
                                f"{channel.id} on that line does not reference the "
                                "group",
                                ("topology", "groups"),
                            )
                        )

    for device in config.topology.devices:
        for channel_id in device.channels:
            if channel_id not in channel_ids:
                problems.append(
                    _problem(
                        "unknown_device_channel",
                        f"device {device.id} references unknown channel {channel_id}",
                        ("topology", "devices"),
                    )
                )

    for link in config.topology.links:
        for endpoint in link.endpoints:
            if endpoint not in entity_ids:
                problems.append(
                    _problem(
                        "unknown_link_endpoint",
                        f"link {link.id} references unknown endpoint {endpoint}",
                        ("topology", "links"),
                    )
                )

    return tuple(problems)


def validate_config_profile(
    config: ConfigProfileSnapshot,
    *,
    include_parameter_values: bool = True,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []

    if config.environment.workspace_id != config.system.workspace_id:
        problems.append(
            _problem(
                "config_profile_workspace_mismatch",
                "environment workspace does not match system workspace",
                ("environment", "workspace_id"),
            )
        )

    entity_ids = {entity.id for entity in config.topology.entities}
    line_ids = {line.id for line in config.topology.lines}
    channel_ids = {channel.id for channel in config.topology.channels}
    group_ids = {group.id for group in config.topology.groups}
    channels_by_id = {channel.id: channel for channel in config.topology.channels}
    instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }

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

    problems.extend(_topology_problems(config))

    for resource in config.routing.resources:
        if resource.kind == "instrument" and resource.id not in instrument_ids:
            problems.append(
                _problem(
                    "unknown_routing_resource_instrument",
                    f"routing resource {resource.id} references unknown instrument",
                    ("system", "routing", "resources"),
                )
            )
        for entity_id in resource.served_entities:
            if entity_id not in entity_ids:
                problems.append(
                    _problem(
                        "unknown_routing_resource_served_entity",
                        f"routing resource {resource.id} serves unknown entity "
                        f"{entity_id}",
                        ("system", "routing", "resources"),
                    )
                )
        for channel_id in resource.channels:
            if channel_id not in channel_ids:
                problems.append(
                    _problem(
                        "unknown_routing_resource_channel",
                        f"routing resource {resource.id} references unknown channel "
                        f"{channel_id}",
                        ("system", "routing", "resources"),
                    )
                )

    routing_context = _RoutingValidationContext(
        resources={resource.id: resource for resource in config.routing.resources},
        entity_ids=entity_ids,
        channel_ids=channel_ids,
        line_ids=line_ids,
        group_ids=group_ids,
        channels_by_id=channels_by_id,
    )
    problems.extend(_routing_edge_problems(config, routing_context))

    for connection in config.connection_profile.connections:
        if connection.instrument_id not in instrument_ids:
            problems.append(
                _problem(
                    "unknown_connection_instrument",
                    f"connection {connection.id} references unknown instrument "
                    f"{connection.instrument_id}",
                    ("connection_profile", "connections"),
                )
            )

    if include_parameter_values:
        problems.extend(resolve_config_parameters(config).problems)

    return tuple(problems)


def validate_config(config: ConfigProfileSnapshot) -> tuple[Problem, ...]:
    return validate_config_profile(config)
