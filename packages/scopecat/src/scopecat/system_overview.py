"""Notebook-facing summaries for configured system topology and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.models.config import ConfigProfileSnapshot


@dataclass(frozen=True)
class SystemEntitySummary:
    id: str
    kind: str | None
    lines: tuple[str, ...]
    channels: tuple[str, ...]
    resources: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SystemLineSummary:
    id: str
    kind: str
    signal: str | None
    endpoints: tuple[str, ...]
    channels: tuple[str, ...]
    groups: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SystemChannelSummary:
    id: str
    kind: str
    device_id: str | None
    line_id: str | None
    signal: str | None
    direction: str | None
    port: str | None
    max_route_ports_per_point: int | None
    groups: tuple[str, ...]
    resources: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SystemGroupSummary:
    id: str
    kind: str
    members: tuple[str, ...]
    max_resources_per_point: int | None
    channels: tuple[str, ...]
    resources: tuple[str, ...]
    entities: tuple[str, ...]
    capabilities: tuple[str, ...]
    binding_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SystemResourceSummary:
    id: str
    kind: str
    capabilities: tuple[str, ...]
    served_entities: tuple[str, ...]
    channels: tuple[str, ...]
    binding_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SystemSummary:
    config_id: str
    system_id: str
    workspace_id: str
    primary_entity_id: str
    entities: tuple[SystemEntitySummary, ...]
    lines: tuple[SystemLineSummary, ...]
    channels: tuple[SystemChannelSummary, ...]
    groups: tuple[SystemGroupSummary, ...]
    resources: tuple[SystemResourceSummary, ...]

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    @property
    def resource_count(self) -> int:
        return len(self.resources)


def build_system_summary(config: ConfigProfileSnapshot) -> SystemSummary:
    topology = config.topology
    routing = config.routing
    entity_ids = {entity.id for entity in topology.entities}
    line_channels: dict[str, list[str]] = {}
    channel_groups: dict[str, tuple[str, ...]] = {}
    channel_resources: dict[str, set[str]] = {}
    group_channels: dict[str, set[str]] = {}
    group_resources: dict[str, set[str]] = {}
    group_entities: dict[str, set[str]] = {}
    group_capabilities: dict[str, set[str]] = {}
    group_binding_count: dict[str, int] = {}
    entity_resources: dict[str, set[str]] = {
        entity_id: set() for entity_id in entity_ids
    }

    for channel in topology.channels:
        channel_groups[channel.id] = tuple(channel.group_ids)
        for group_id in channel.group_ids:
            group_channels.setdefault(group_id, set()).add(channel.id)
        if channel.line_id is not None:
            line_channels.setdefault(channel.line_id, []).append(channel.id)

    for group in topology.groups:
        for member in group.members:
            if member in channel_groups:
                group_channels.setdefault(group.id, set()).add(member)
            group_channels.setdefault(group.id, set()).update(
                line_channels.get(member, ())
            )

    for resource in routing.resources:
        for entity_id in resource.served_entities:
            if entity_id in entity_resources:
                entity_resources[entity_id].add(resource.id)
        for channel_id in resource.channels:
            channel_resources.setdefault(channel_id, set()).add(resource.id)

    binding_count_by_resource = {resource.id: 0 for resource in routing.resources}
    for edge in routing.edges:
        binding_count_by_resource[edge.resource_id] = binding_count_by_resource.get(
            edge.resource_id, 0
        ) + len(edge.bindings)
        for entity_id in edge.entity_ids:
            if entity_id in entity_resources:
                entity_resources[entity_id].add(edge.resource_id)
        for channel_id in edge.channels:
            channel_resources.setdefault(channel_id, set()).add(edge.resource_id)
        for binding in edge.bindings:
            if binding.entity_id in entity_resources:
                entity_resources[binding.entity_id].add(edge.resource_id)
            channel_resources.setdefault(binding.channel_id, set()).add(
                edge.resource_id
            )
            binding_group_ids = tuple(
                binding.group_ids or channel_groups.get(binding.channel_id, ())
            )
            for group_id in binding_group_ids:
                group_channels.setdefault(group_id, set()).add(binding.channel_id)
                group_resources.setdefault(group_id, set()).add(edge.resource_id)
                group_entities.setdefault(group_id, set()).add(binding.entity_id)
                if binding.capability is not None:
                    group_capabilities.setdefault(group_id, set()).add(
                        binding.capability
                    )
                else:
                    group_capabilities.setdefault(group_id, set()).update(
                        edge.capabilities
                    )
                group_binding_count[group_id] = group_binding_count.get(group_id, 0) + 1

    entity_lines: dict[str, list[str]] = {entity_id: [] for entity_id in entity_ids}
    for line in topology.lines:
        for endpoint in line.endpoints:
            if endpoint in entity_lines:
                entity_lines[endpoint].append(line.id)

    entity_channels = {
        entity_id: tuple(
            channel_id
            for line_id in line_ids
            for channel_id in line_channels.get(line_id, ())
        )
        for entity_id, line_ids in entity_lines.items()
    }

    return SystemSummary(
        config_id=config.id,
        system_id=config.system.id,
        workspace_id=config.workspace_id,
        primary_entity_id=config.primary_entity_id,
        entities=tuple(
            SystemEntitySummary(
                id=entity.id,
                kind=entity.kind,
                lines=tuple(entity_lines.get(entity.id, ())),
                channels=entity_channels.get(entity.id, ()),
                resources=tuple(sorted(entity_resources.get(entity.id, ()))),
                metadata=dict(entity.metadata),
            )
            for entity in topology.entities
        ),
        lines=tuple(
            SystemLineSummary(
                id=line.id,
                kind=line.kind,
                signal=line.signal,
                endpoints=tuple(line.endpoints),
                channels=tuple(line_channels.get(line.id, ())),
                groups=tuple(
                    sorted(
                        {
                            group_id
                            for channel_id in line_channels.get(line.id, ())
                            for group_id in channel_groups.get(channel_id, ())
                        }
                    )
                ),
                metadata=dict(line.metadata),
            )
            for line in topology.lines
        ),
        channels=tuple(
            SystemChannelSummary(
                id=channel.id,
                kind=channel.kind,
                device_id=channel.device_id,
                line_id=channel.line_id,
                signal=channel.signal,
                direction=channel.direction,
                port=channel.port,
                max_route_ports_per_point=channel.max_route_ports_per_point,
                groups=tuple(channel.group_ids),
                resources=tuple(sorted(channel_resources.get(channel.id, ()))),
                metadata=dict(channel.metadata),
            )
            for channel in topology.channels
        ),
        groups=tuple(
            SystemGroupSummary(
                id=group.id,
                kind=group.kind,
                members=tuple(group.members),
                max_resources_per_point=group.max_resources_per_point,
                channels=tuple(sorted(group_channels.get(group.id, ()))),
                resources=tuple(sorted(group_resources.get(group.id, ()))),
                entities=tuple(sorted(group_entities.get(group.id, ()))),
                capabilities=tuple(sorted(group_capabilities.get(group.id, ()))),
                binding_count=group_binding_count.get(group.id, 0),
                metadata=dict(group.metadata),
            )
            for group in topology.groups
        ),
        resources=tuple(
            SystemResourceSummary(
                id=resource.id,
                kind=resource.kind,
                capabilities=tuple(resource.capabilities),
                served_entities=tuple(resource.served_entities),
                channels=tuple(resource.channels),
                binding_count=binding_count_by_resource.get(resource.id, 0),
                metadata=dict(resource.metadata),
            )
            for resource in routing.resources
        ),
    )


__all__ = [
    "SystemChannelSummary",
    "SystemEntitySummary",
    "SystemGroupSummary",
    "SystemLineSummary",
    "SystemResourceSummary",
    "SystemSummary",
    "build_system_summary",
]
