"""Validate point-local resource sharing after symbolic routes are bound."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat._compiler.bound import BoundRoute
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import ConfigProfileSnapshot


def validate_route_constraints(
    routes_by_point: Mapping[int, Sequence[BoundRoute]],
    *,
    config: ConfigProfileSnapshot,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    group_limits = {
        group.id: group.max_resources_per_point for group in config.topology.groups
    }
    channel_limits = {
        channel.id: channel.max_route_ports_per_point
        for channel in config.topology.channels
    }
    for point_index, routes in routes_by_point.items():
        diagnostics.extend(_duplicate_ports(point_index, routes))
        diagnostics.extend(
            _shared_groups(point_index, routes, group_limits=group_limits)
        )
        diagnostics.extend(
            _shared_channels(point_index, routes, channel_limits=channel_limits)
        )
    return diagnostics


def _duplicate_ports(
    point_index: int,
    routes: Sequence[BoundRoute],
) -> list[Diagnostic]:
    by_port: dict[str, list[BoundRoute]] = {}
    for route in routes:
        by_port.setdefault(route.port_id, []).append(route)
    diagnostics: list[Diagnostic] = []
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
        diagnostics.append(
            _diagnostic(
                "routing_port_resolved_multiple_bindings",
                f"route port {port_id} resolved to multiple bindings for "
                f"point {point_index}",
                f"points.{point_index}.routes.{port_id}",
            )
        )
    return diagnostics


def _shared_groups(
    point_index: int,
    routes: Sequence[BoundRoute],
    *,
    group_limits: Mapping[str, int | None],
) -> list[Diagnostic]:
    resources_by_group: dict[str, set[str]] = {}
    for route in routes:
        for binding in route.channel_bindings:
            for group_id in binding.group_ids:
                resources_by_group.setdefault(group_id, set()).add(route.resource_id)
    diagnostics: list[Diagnostic] = []
    for group_id, resource_ids in sorted(resources_by_group.items()):
        limit = group_limits.get(group_id, 1)
        if limit is None or len(resource_ids) <= limit:
            continue
        diagnostics.append(
            _diagnostic(
                "routing_shared_group_resource_conflict",
                f"shared group {group_id} is used by {len(resource_ids)} resources "
                f"at point {point_index}, above its limit of {limit}: "
                + ", ".join(sorted(resource_ids)),
                f"points.{point_index}.routes",
            )
        )
    return diagnostics


def _shared_channels(
    point_index: int,
    routes: Sequence[BoundRoute],
    *,
    channel_limits: Mapping[str, int | None],
) -> list[Diagnostic]:
    ports_by_channel: dict[str, set[str]] = {}
    for route in routes:
        for binding in route.channel_bindings:
            ports_by_channel.setdefault(binding.channel_id, set()).add(route.port_id)
    diagnostics: list[Diagnostic] = []
    for channel_id, port_ids in sorted(ports_by_channel.items()):
        limit = channel_limits.get(channel_id, 1)
        if limit is None or len(port_ids) <= limit:
            continue
        diagnostics.append(
            _diagnostic(
                "routing_channel_shared_by_ports",
                f"channel {channel_id} is selected by {len(port_ids)} route ports "
                f"at point {point_index}, above its limit of {limit}: "
                + ", ".join(sorted(port_ids)),
                f"points.{point_index}.routes",
            )
        )
    return diagnostics


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["validate_route_constraints"]
