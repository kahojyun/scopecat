"""Internal routing view over accepted configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingResource,
)
from scopecat.records.entity import EntityRef


@dataclass(frozen=True)
class ResourceBinding:
    """Resolved logical resource binding for a port at runtime lowering time."""

    port_id: LogicalResourcePortId
    resource_id: PhysicalResourceId
    resource_kind: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    served_entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


@dataclass(frozen=True)
class PhysicalResourceBinding:
    """Validated direct binding to one configured physical resource."""

    resource_id: PhysicalResourceId
    resource_kind: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
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
        port_id: LogicalResourcePortId,
        capabilities: Sequence[str],
        entity_ids: Sequence[str] = (),
        fixed_resource_id: PhysicalResourceId | None = None,
    ) -> ResourceBinding:
        selected_capabilities = tuple(capabilities)
        selected_entity_ids = tuple(dict.fromkeys(entity_ids))
        if fixed_resource_id is not None:
            resource = self.resource(fixed_resource_id)
            if resource is None:
                raise RoutingError(
                    "module_resource_port_not_found",
                    (
                        f"resource port {port_id} references unknown resource "
                        f"{fixed_resource_id}"
                    ),
                )
            if not self._resource_satisfies(
                resource,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
            ):
                raise RoutingError(
                    "module_resource_port_entity_mismatch",
                    f"resource {fixed_resource_id} cannot satisfy port {port_id}",
                )
            return ResourceBinding(
                port_id=port_id,
                resource_id=fixed_resource_id,
                resource_kind=resource.kind,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
                served_entity_ids=tuple(
                    sorted(self._served_entity_ids(resource, selected_capabilities))
                ),
                product_axis_order=selected_entity_ids,
                channel_bindings=self._channel_bindings(
                    resource,
                    capabilities=selected_capabilities,
                    entity_ids=selected_entity_ids,
                ),
            )

        candidates = [
            PhysicalResourceId(resource.id)
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
                f"{', '.join(candidate.value for candidate in candidates)}",
            )
        selected_resource = self.resource(candidates[0])
        if selected_resource is None:
            raise AssertionError("selected routing resource disappeared")
        return ResourceBinding(
            port_id=port_id,
            resource_id=candidates[0],
            resource_kind=selected_resource.kind,
            capabilities=selected_capabilities,
            entity_ids=selected_entity_ids,
            served_entity_ids=tuple(
                sorted(
                    self._served_entity_ids(
                        selected_resource,
                        selected_capabilities,
                    )
                )
            ),
            product_axis_order=selected_entity_ids,
            channel_bindings=self._channel_bindings(
                selected_resource,
                capabilities=selected_capabilities,
                entity_ids=selected_entity_ids,
            ),
        )

    def route_point(
        self,
        *,
        port_id: LogicalResourcePortId,
        capabilities: Sequence[str],
        entity_values: Sequence[object] = (),
        fixed_resource_id: PhysicalResourceId | None = None,
    ) -> ResourceBinding:
        return self.route(
            port_id=port_id,
            capabilities=capabilities,
            entity_ids=_entity_ids(entity_values),
            fixed_resource_id=fixed_resource_id,
        )

    def bind_physical(
        self,
        *,
        resource_id: PhysicalResourceId,
        capabilities: Sequence[str] = (),
        entity_values: Sequence[object] = (),
    ) -> PhysicalResourceBinding:
        selected_capabilities = tuple(capabilities)
        selected_entity_ids = _entity_ids(entity_values)
        resource = self.resource(resource_id)
        if resource is None:
            raise RoutingError(
                "physical_resource_not_found",
                f"unknown physical resource {resource_id.value!r}",
            )
        if not self._resource_satisfies(
            resource,
            capabilities=selected_capabilities,
            entity_ids=selected_entity_ids,
        ):
            raise RoutingError(
                "physical_resource_contract_mismatch",
                f"physical resource {resource_id.value!r} cannot satisfy the "
                "required capabilities and entities",
            )
        return PhysicalResourceBinding(
            resource_id=resource_id,
            resource_kind=resource.kind,
            capabilities=selected_capabilities,
            entity_ids=selected_entity_ids,
            channel_bindings=(
                self._channel_bindings(
                    resource,
                    capabilities=selected_capabilities,
                    entity_ids=selected_entity_ids,
                )
                if selected_entity_ids
                else ()
            ),
        )

    def resource(self, resource_id: PhysicalResourceId) -> RoutingResource | None:
        for resource in self.resources:
            if resource.id == resource_id.value:
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
        if not capabilities:
            served = set(resource.served_entities)
            for edge in self.edges:
                if edge.resource_id != resource.id:
                    continue
                served.update(edge.entity_ids)
                served.update(binding.entity_id for binding in edge.bindings)
            return served
        served: set[str] = set()
        for capability in capabilities:
            capability_entities: set[str] = set()
            for edge in self.edges:
                if edge.resource_id != resource.id:
                    continue
                capability_entities.update(
                    _edge_entities_for_capability(edge, capability)
                )
            served.update(capability_entities or resource.served_entities)
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
            if not _edge_relevant_to_capabilities(edge, capabilities):
                continue
            for binding in edge.bindings:
                if wanted and binding.entity_id not in wanted:
                    continue
                for capability in _effective_binding_capabilities(
                    binding,
                    edge=edge,
                    selected_capabilities=capabilities,
                ):
                    selected.append(
                        self._enriched_binding(
                            binding.model_copy(update={"capability": capability})
                        )
                    )
        channels_by_entity = dict(
            zip(
                resource.served_entities,
                resource.channels,
                strict=False,
            )
        )
        fallback: tuple[RoutingChannelBinding, ...]
        fallback_entity_ids = entity_ids or tuple(
            entity_id
            for entity_id in resource.served_entities
            if entity_id in self._served_entity_ids(resource, capabilities)
        )
        if channels_by_entity:
            fallback = tuple(
                RoutingChannelBinding(
                    entity_id=entity_id,
                    channel_id=channels_by_entity[entity_id],
                    line_id=self._channel_line(channels_by_entity[entity_id]),
                    group_ids=list(self._channel_groups(channels_by_entity[entity_id])),
                )
                for entity_id in fallback_entity_ids
                if entity_id in channels_by_entity
            )
        elif not fallback_entity_ids:
            fallback = ()
        else:
            fallback = tuple(
                RoutingChannelBinding(
                    entity_id=entity_id,
                    channel_id=channel_id,
                    line_id=self._channel_line(channel_id),
                    group_ids=list(self._channel_groups(channel_id)),
                )
                for entity_id, channel_id in zip(
                    fallback_entity_ids,
                    resource.channels,
                    strict=False,
                )
            )
        merged: list[RoutingChannelBinding] = []
        seen: set[tuple[str, str, str | None, str | None, tuple[str, ...]]] = set()
        for binding in selected:
            identity = _channel_binding_identity(binding)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(binding)
        fallback_capabilities: tuple[str | None, ...] = (
            capabilities or tuple(resource.capabilities) or (None,)
        )
        for capability in fallback_capabilities:
            if _resource_capability_has_explicit_bindings(
                self.edges,
                resource_id=resource.id,
                capability=capability,
            ):
                continue
            for binding in fallback:
                candidate = binding.model_copy(update={"capability": capability})
                identity = _channel_binding_identity(candidate)
                if identity in seen:
                    continue
                seen.add(identity)
                merged.append(candidate)
        if not entity_ids:
            return tuple(merged)
        merged_by_entity: dict[str, list[RoutingChannelBinding]] = {}
        for binding in merged:
            merged_by_entity.setdefault(binding.entity_id, []).append(binding)
        return tuple(
            binding
            for entity_id in entity_ids
            for binding in merged_by_entity.get(entity_id, ())
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


def _edge_relevant_to_capabilities(
    edge: RoutingEdge,
    capabilities: tuple[str, ...],
) -> bool:
    if not edge.capabilities or not capabilities:
        return True
    return any(capability in edge.capabilities for capability in capabilities)


def _effective_binding_capabilities(
    binding: RoutingChannelBinding,
    *,
    edge: RoutingEdge,
    selected_capabilities: tuple[str, ...],
) -> tuple[str | None, ...]:
    if binding.capability is not None:
        if selected_capabilities and binding.capability not in selected_capabilities:
            return ()
        return (binding.capability,)
    if edge.capabilities:
        return tuple(
            capability
            for capability in edge.capabilities
            if not selected_capabilities or capability in selected_capabilities
        )
    return (None,)


def _resource_capability_has_explicit_bindings(
    edges: Sequence[RoutingEdge],
    *,
    resource_id: str,
    capability: str | None,
) -> bool:
    return any(
        _binding_applies_to_capability(edge, binding, capability)
        for edge in edges
        if edge.resource_id == resource_id
        for binding in edge.bindings
    )


def _binding_applies_to_capability(
    edge: RoutingEdge,
    binding: RoutingChannelBinding,
    capability: str | None,
) -> bool:
    if capability is None:
        return True
    if binding.capability is not None:
        return binding.capability == capability
    return not edge.capabilities or capability in edge.capabilities


def _edge_entities_for_capability(
    edge: RoutingEdge,
    capability: str,
) -> set[str]:
    if edge.capabilities and capability not in edge.capabilities:
        return {
            binding.entity_id
            for binding in edge.bindings
            if binding.capability == capability
        }
    relevant_bindings = {
        binding.entity_id
        for binding in edge.bindings
        if _binding_applies_to_capability(edge, binding, capability)
    }
    if edge.capabilities or relevant_bindings or not edge.bindings:
        return {*edge.entity_ids, *relevant_bindings}
    return relevant_bindings


def _physical_channel_binding_identity(
    binding: RoutingChannelBinding,
) -> tuple[str, str, str | None, tuple[str, ...]]:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        tuple(sorted(binding.group_ids)),
    )


def _channel_binding_identity(
    binding: RoutingChannelBinding,
) -> tuple[str, str, str | None, str | None, tuple[str, ...]]:
    physical = _physical_channel_binding_identity(binding)
    return (*physical[:3], binding.capability, physical[3])


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
            entity_ids.extend(_entity_ids(value))
        else:
            raise RoutingError(
                "module_resource_entity_invalid",
                f"route entity must resolve to an entity reference, got {value!r}",
            )
    return tuple(dict.fromkeys(entity_ids))


__all__ = [
    "PhysicalResourceBinding",
    "ResourceBinding",
    "RoutingError",
    "RoutingView",
]
