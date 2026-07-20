"""Structured configuration checks."""

from __future__ import annotations

from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
)


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
    config: ConfigProfileSnapshot,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    path = ("system", "routing", "bindings")
    instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    entity_ids = {entity.id for entity in config.topology.entities}
    channels = {channel.id: channel for channel in config.topology.channels}

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
        channel = channels.get(binding.channel_id)
        if channel is None:
            problems.append(
                _problem(
                    "unknown_routing_binding_channel",
                    f"routing binding references unknown channel {binding.channel_id}",
                    path,
                )
            )
            continue
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

    problems.extend(_routing_binding_problems(config))

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
