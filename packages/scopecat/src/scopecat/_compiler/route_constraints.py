"""Validate point-local resource sharing after symbolic routes are bound."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat._compiler.bound import BoundRoute
from scopecat._compiler.problems import compiler_problem
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.problems import ModelLocation, Problem, ProblemCategory, model_location


def validate_route_constraints(
    routes_by_point: Mapping[int, Sequence[BoundRoute]],
    *,
    config: ConfigProfileSnapshot,
) -> list[Problem]:
    problems: list[Problem] = []
    group_limits = {
        group.id: group.max_resources_per_point for group in config.topology.groups
    }
    channel_limits = {
        channel.id: channel.max_route_ports_per_point
        for channel in config.topology.channels
    }
    for point_index, routes in routes_by_point.items():
        problems.extend(_duplicate_ports(point_index, routes))
        problems.extend(_shared_groups(point_index, routes, group_limits=group_limits))
        problems.extend(
            _shared_channels(point_index, routes, channel_limits=channel_limits)
        )
    return problems


def _duplicate_ports(
    point_index: int,
    routes: Sequence[BoundRoute],
) -> list[Problem]:
    by_port: dict[str, list[BoundRoute]] = {}
    for route in routes:
        by_port.setdefault(route.port_id, []).append(route)
    problems: list[Problem] = []
    for port_id, bindings in by_port.items():
        signatures = {
            (
                binding.resource_id,
                binding.capabilities,
                binding.entity_ids,
                binding.product_axis_order,
            )
            for binding in bindings
        }
        if len(signatures) <= 1:
            continue
        problems.append(
            _problem(
                "routing_port_resolved_multiple_bindings",
                f"route port {port_id} resolved to multiple bindings for "
                f"point {point_index}",
                model_location("points", point_index, "routes", port_id),
            )
        )
    return problems


def _shared_groups(
    point_index: int,
    routes: Sequence[BoundRoute],
    *,
    group_limits: Mapping[str, int | None],
) -> list[Problem]:
    resources_by_group: dict[str, set[str]] = {}
    for route in routes:
        for binding in route.channel_bindings:
            for group_id in binding.group_ids:
                resources_by_group.setdefault(group_id, set()).add(route.resource_id)
    problems: list[Problem] = []
    for group_id, resource_ids in sorted(resources_by_group.items()):
        limit = group_limits.get(group_id, 1)
        if limit is None or len(resource_ids) <= limit:
            continue
        problems.append(
            _problem(
                "routing_shared_group_resource_conflict",
                f"shared group {group_id} is used by {len(resource_ids)} resources "
                f"at point {point_index}, above its limit of {limit}: "
                + ", ".join(sorted(resource_ids)),
                model_location("points", point_index, "routes"),
            )
        )
    return problems


def _shared_channels(
    point_index: int,
    routes: Sequence[BoundRoute],
    *,
    channel_limits: Mapping[str, int | None],
) -> list[Problem]:
    ports_by_channel: dict[str, set[str]] = {}
    for route in routes:
        for binding in route.channel_bindings:
            ports_by_channel.setdefault(binding.channel_id, set()).add(route.port_id)
    problems: list[Problem] = []
    for channel_id, port_ids in sorted(ports_by_channel.items()):
        limit = channel_limits.get(channel_id, 1)
        if limit is None or len(port_ids) <= limit:
            continue
        problems.append(
            _problem(
                "routing_channel_shared_by_ports",
                f"channel {channel_id} is selected by {len(port_ids)} route ports "
                f"at point {point_index}, above its limit of {limit}: "
                + ", ".join(sorted(port_ids)),
                model_location("points", point_index, "routes"),
            )
        )
    return problems


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        category=ProblemCategory.CONFLICT,
    )


__all__ = ["validate_route_constraints"]
