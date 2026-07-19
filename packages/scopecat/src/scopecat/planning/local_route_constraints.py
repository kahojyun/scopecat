"""Validate point-local resource sharing after symbolic routes are bound."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.products import ProductAxisDef
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.kernel.resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat.kernel.state import StateValue
from scopecat.measurements.results import MeasurementDType
from scopecat.records.config import ConfigProfileSnapshot, RoutingChannelBinding

type _ChannelConsumerId = LogicalResourcePortId | PhysicalResourceId


def _empty_metadata() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class PendingRoute:
    """One short-lived physical route used while binding a point program."""

    port_id: LogicalResourcePortId
    resource_id: PhysicalResourceId
    resource_kind: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    served_entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingStateField:
    field_path: str
    value: StateValue
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingResourceState:
    resource_id: PhysicalResourceId
    capability_id: str
    fields: tuple[PendingStateField, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingCollectionRequest:
    product_use_id: ProductUseId
    product_id: ProductId
    provider_key: str
    capability: str | None
    unit: str | None
    dtype: MeasurementDType
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()
    axes: tuple[ProductAxisDef, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class PendingCollect:
    resource_id: PhysicalResourceId
    requests: tuple[PendingCollectionRequest, ...]


@dataclass(frozen=True, slots=True)
class _ChannelUse:
    resource_id: PhysicalResourceId
    consumer_id: _ChannelConsumerId
    bindings: tuple[RoutingChannelBinding, ...]


def validate_point_resource_constraints(
    point_index: int,
    routes: Sequence[PendingRoute],
    desired_state: Sequence[PendingResourceState],
    collects: Sequence[PendingCollect],
    *,
    config: ConfigProfileSnapshot,
) -> list[Problem]:
    group_limits = {
        group.id: group.max_resources_per_point for group in config.topology.groups
    }
    channel_limits = {
        channel.id: channel.max_route_ports_per_point
        for channel in config.topology.channels
    }
    channel_uses = _channel_uses(routes, desired_state, collects)
    return [
        *_duplicate_ports(point_index, routes),
        *_shared_groups(
            point_index,
            channel_uses,
            group_limits=group_limits,
        ),
        *_shared_channels(
            point_index,
            channel_uses,
            channel_limits=channel_limits,
        ),
    ]


def _channel_uses(
    routes: Sequence[PendingRoute],
    desired_state: Sequence[PendingResourceState],
    collects: Sequence[PendingCollect],
) -> tuple[_ChannelUse, ...]:
    uses = [
        _ChannelUse(
            resource_id=route.resource_id,
            consumer_id=route.port_id,
            bindings=route.channel_bindings,
        )
        for route in routes
        if route.channel_bindings
    ]
    uses.extend(
        _ChannelUse(
            resource_id=state.resource_id,
            consumer_id=field.resource_port_id or state.resource_id,
            bindings=field.channel_bindings,
        )
        for state in desired_state
        for field in state.fields
        if field.channel_bindings
    )
    uses.extend(
        _ChannelUse(
            resource_id=collect.resource_id,
            consumer_id=request.resource_port_id or collect.resource_id,
            bindings=request.channel_bindings,
        )
        for collect in collects
        for request in collect.requests
        if request.channel_bindings
    )
    return tuple(uses)


def _duplicate_ports(
    point_index: int,
    routes: Sequence[PendingRoute],
) -> list[Problem]:
    by_port: dict[LogicalResourcePortId, list[PendingRoute]] = {}
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
                "route port "
                f"{port_id.qualified_name} resolved to multiple bindings "
                f"for point {point_index}",
                model_location("points", point_index, "routes", port_id.qualified_name),
            )
        )
    return problems


def _shared_groups(
    point_index: int,
    uses: Sequence[_ChannelUse],
    *,
    group_limits: Mapping[str, int | None],
) -> list[Problem]:
    resources_by_group: dict[str, set[PhysicalResourceId]] = {}
    for use in uses:
        for binding in use.bindings:
            for group_id in binding.group_ids:
                resources_by_group.setdefault(group_id, set()).add(use.resource_id)
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
                + ", ".join(sorted(item.value for item in resource_ids)),
                model_location("points", point_index, "routes"),
            )
        )
    return problems


def _shared_channels(
    point_index: int,
    uses: Sequence[_ChannelUse],
    *,
    channel_limits: Mapping[str, int | None],
) -> list[Problem]:
    consumers_by_channel: dict[str, set[_ChannelConsumerId]] = {}
    for use in uses:
        for binding in use.bindings:
            consumers_by_channel.setdefault(binding.channel_id, set()).add(
                use.consumer_id
            )
    problems: list[Problem] = []
    for channel_id, consumer_ids in sorted(consumers_by_channel.items()):
        limit = channel_limits.get(channel_id, 1)
        if limit is None or len(consumer_ids) <= limit:
            continue
        problems.append(
            _problem(
                "routing_channel_shared_by_ports",
                f"channel {channel_id} is selected by {len(consumer_ids)} resource "
                "consumers "
                f"at point {point_index}, above its limit of {limit}: "
                + ", ".join(
                    sorted(_channel_consumer_display(item) for item in consumer_ids)
                ),
                model_location("points", point_index, "routes"),
            )
        )
    return problems


def _channel_consumer_display(consumer_id: _ChannelConsumerId) -> str:
    if isinstance(consumer_id, LogicalResourcePortId):
        return f"port:{consumer_id.qualified_name}"
    return f"physical:{consumer_id.value}"


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        category=ProblemCategory.CONFLICT,
    )
