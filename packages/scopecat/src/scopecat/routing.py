"""Internal routing view over accepted configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.models.config import (
    ConfigProfileSnapshot,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingResource,
)
from scopecat.models.entity import EntityRef


@dataclass(frozen=True)
class ResourceBinding:
    """Resolved logical resource binding for a port at runtime lowering time."""

    port_id: str
    resource_id: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


class RoutingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoutingView:
    """Resolves logical resources from config-declared capabilities and entities."""

    resources: tuple[RoutingResource, ...]
    edges: tuple[RoutingEdge, ...] = ()
    channel_lines_by_id: dict[str, str | None] | None = None
    channel_groups_by_id: dict[str, tuple[str, ...]] | None = None

    @classmethod
    def from_config(cls, config: ConfigProfileSnapshot) -> RoutingView:
        resources = tuple(config.routing.resources)
        edges = tuple(config.routing.edges)
        return cls(
            resources=resources,
            edges=edges,
            channel_lines_by_id={
                channel.id: channel.line_id for channel in config.topology.channels
            },
            channel_groups_by_id={
                channel.id: tuple(channel.group_ids)
                for channel in config.topology.channels
            },
        )

    def route(
        self,
        *,
        port_id: str,
        capabilities: Sequence[str],
        entity_ids: Sequence[str] = (),
        resource_id: str | None = None,
    ) -> ResourceBinding:
        selected_capabilities = tuple(capabilities)
        selected_entity_ids = tuple(dict.fromkeys(entity_ids))
        if resource_id is not None:
            resource = self.resource(resource_id)
            if resource is None:
                raise RoutingError(
                    "module_resource_port_not_found",
                    (
                        f"resource port {port_id} references unknown resource "
                        f"{resource_id}"
                    ),
                )
            if not self._resource_satisfies(
                resource,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
            ):
                raise RoutingError(
                    "module_resource_port_entity_mismatch",
                    f"resource {resource_id} cannot satisfy port {port_id}",
                )
            return ResourceBinding(
                port_id=port_id,
                resource_id=resource_id,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
                product_axis_order=selected_entity_ids,
                channel_bindings=self._channel_bindings(
                    resource,
                    capabilities=selected_capabilities,
                    entity_ids=selected_entity_ids,
                ),
            )

        candidates = [
            resource.id
            for resource in self.resources
            if self._resource_satisfies(
                resource,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
            )
        ]
        if not candidates:
            raise RoutingError(
                "module_resource_port_not_found",
                f"no resource satisfies port {port_id}",
            )
        if len(candidates) > 1:
            raise RoutingError(
                "module_resource_port_ambiguous",
                f"resource port {port_id} matches multiple resources: "
                f"{', '.join(candidates)}",
            )
        return ResourceBinding(
            port_id=port_id,
            resource_id=candidates[0],
            capabilities=selected_capabilities,
            entity_ids=selected_entity_ids,
            product_axis_order=selected_entity_ids,
            channel_bindings=self._channel_bindings(
                self.resource(candidates[0]),
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
            ),
        )

    def route_point(
        self,
        *,
        port_id: str,
        capabilities: Sequence[str],
        entity_values: Sequence[object] = (),
        resource_id: str | None = None,
    ) -> ResourceBinding:
        return self.route(
            port_id=port_id,
            capabilities=capabilities,
            entity_ids=_entity_ids(entity_values),
            resource_id=resource_id,
        )

    def resource(self, resource_id: str) -> RoutingResource | None:
        for resource in self.resources:
            if resource.id == resource_id:
                return resource
        return None

    def _resource_satisfies(
        self,
        resource: RoutingResource,
        *,
        capabilities: tuple[str, ...],
        entity_ids: tuple[str, ...],
    ) -> bool:
        if not all(capability in resource.capabilities for capability in capabilities):
            return False
        if not entity_ids:
            return True
        served_entity_ids = self._served_entity_ids(resource, capabilities)
        return all(entity_id in served_entity_ids for entity_id in entity_ids)

    def _served_entity_ids(
        self,
        resource: RoutingResource,
        capabilities: tuple[str, ...],
    ) -> set[str]:
        served = set(resource.served_entities)
        for edge in self.edges:
            if edge.resource_id != resource.id:
                continue
            if not _edge_satisfies_capabilities(edge, capabilities):
                continue
            served.update(edge.entity_ids)
            served.update(binding.entity_id for binding in edge.bindings)
        return served

    def _channel_bindings(
        self,
        resource: RoutingResource | None,
        *,
        capabilities: tuple[str, ...],
        entity_ids: tuple[str, ...],
    ) -> tuple[RoutingChannelBinding, ...]:
        if resource is None:
            return ()
        selected: list[RoutingChannelBinding] = []
        wanted = set(entity_ids)
        for edge in self.edges:
            if edge.resource_id != resource.id:
                continue
            if not _edge_satisfies_capabilities(edge, capabilities):
                continue
            for binding in edge.bindings:
                if wanted and binding.entity_id not in wanted:
                    continue
                if (
                    binding.capability is not None
                    and binding.capability not in capabilities
                ):
                    continue
                selected.append(self._enriched_binding(binding))
        if selected:
            if entity_ids:
                selected_by_entity: dict[str, list[RoutingChannelBinding]] = {}
                for binding in selected:
                    selected_by_entity.setdefault(binding.entity_id, []).append(binding)
                return tuple(
                    binding
                    for entity_id in entity_ids
                    for binding in selected_by_entity.get(entity_id, ())
                )
            return tuple(selected)
        channels_by_entity = dict(
            zip(
                resource.served_entities,
                resource.channels,
                strict=False,
            )
        )
        if channels_by_entity:
            if not entity_ids:
                return tuple(
                    RoutingChannelBinding(
                        entity_id=entity_id,
                        channel_id=channel_id,
                        line_id=self._channel_line(channel_id),
                        group_ids=list(self._channel_groups(channel_id)),
                    )
                    for entity_id, channel_id in channels_by_entity.items()
                )
            return tuple(
                RoutingChannelBinding(
                    entity_id=entity_id,
                    channel_id=channels_by_entity[entity_id],
                    line_id=self._channel_line(channels_by_entity[entity_id]),
                    group_ids=list(self._channel_groups(channels_by_entity[entity_id])),
                )
                for entity_id in entity_ids
                if entity_id in channels_by_entity
            )
        if not entity_ids:
            return ()
        return tuple(
            RoutingChannelBinding(
                entity_id=entity_id,
                channel_id=channel_id,
                line_id=self._channel_line(channel_id),
                group_ids=list(self._channel_groups(channel_id)),
            )
            for entity_id, channel_id in zip(
                entity_ids,
                resource.channels,
                strict=False,
            )
        )

    def _enriched_binding(
        self,
        binding: RoutingChannelBinding,
    ) -> RoutingChannelBinding:
        channel_line = self._channel_line(binding.channel_id)
        channel_groups = self._channel_groups(binding.channel_id)
        has_declared_topology = binding.line_id is not None and bool(binding.group_ids)
        has_inferred_topology = channel_line is not None or bool(channel_groups)
        if has_declared_topology or not has_inferred_topology:
            return binding
        return binding.model_copy(
            update={
                "line_id": binding.line_id or channel_line,
                "group_ids": list(binding.group_ids or channel_groups),
            }
        )

    def _channel_line(self, channel_id: str) -> str | None:
        if self.channel_lines_by_id is None:
            return None
        return self.channel_lines_by_id.get(channel_id)

    def _channel_groups(self, channel_id: str) -> tuple[str, ...]:
        if self.channel_groups_by_id is None:
            return ()
        return self.channel_groups_by_id.get(channel_id, ())


def _edge_satisfies_capabilities(
    edge: RoutingEdge,
    capabilities: tuple[str, ...],
) -> bool:
    if not edge.capabilities:
        return True
    return all(capability in edge.capabilities for capability in capabilities)


def _entity_ids(values: Sequence[object]) -> tuple[str, ...]:
    entity_ids: list[str] = []
    for value in values:
        if isinstance(value, EntityRef):
            if not value.id:
                raise RoutingError(
                    "module_resource_entity_invalid",
                    "route entity id must be non-empty",
                )
            entity_ids.append(value.id)
        elif isinstance(value, str) and value:
            entity_ids.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            if not value:
                raise RoutingError(
                    "module_resource_entity_invalid",
                    "route entity series must not be empty",
                )
            entity_ids.extend(_entity_ids(cast("Sequence[object]", value)))
        else:
            raise RoutingError(
                "module_resource_entity_invalid",
                f"route entity must resolve to an entity reference, got {value!r}",
            )
    return tuple(dict.fromkeys(entity_ids))


__all__ = ["ResourceBinding", "RoutingError", "RoutingView"]
