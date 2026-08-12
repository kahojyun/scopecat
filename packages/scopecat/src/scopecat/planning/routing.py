"""Static physical resource manifests over accepted configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.resource_identity import (
    DEFAULT_RESOURCE_ROLE,
    LogicalResourcePortId,
    ResourceRoleSelector,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    ResourceRoute,
    RoutingEndpoint,
)
from scopecat.records.instrument import CommandChannelBinding


@dataclass(frozen=True)
class ResourceBinding:
    """One selected route, including its logical-to-physical provenance."""

    port_id: LogicalResourcePortId
    requested_role: ResourceRoleSelector
    route_id: str
    route_role_id: str | None
    instrument_id: str
    endpoints: tuple[RoutingEndpoint, ...] = ()
    component_path: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True)
class ResourcePortManifest:
    """Frozen route candidates for one logical resource contract.

    Point-local entity values may only narrow this manifest. They cannot
    discover providers, construct new physical paths, or change route
    ownership after target preparation.
    """

    port_id: LogicalResourcePortId
    role: ResourceRoleSelector
    interfaces: tuple[InterfaceId, ...]
    routes: tuple[ResourceRoute, ...]

    @property
    def candidate_instrument_ids(self) -> tuple[str, ...]:
        """Return instruments that may satisfy this port for some entity scope."""

        return tuple(
            dict.fromkeys(
                route.instrument_id
                for route in self.routes
                if all(
                    any(
                        endpoint.interface_id == interface
                        for endpoint in route.endpoints
                    )
                    for interface in self.interfaces
                )
            )
        )

    def select_one(
        self,
        entity_ids: Sequence[str] = (),
    ) -> ResourceBinding:
        """Select exactly one configured route for the complete entity scope."""

        selected_entity_ids = tuple(dict.fromkeys(entity_ids))
        candidates: tuple[ResourceRoute, ...] = tuple(
            route
            for route in self.routes
            if _route_satisfies(
                route,
                interfaces=self.interfaces,
                entity_ids=selected_entity_ids,
            )
        )
        role_description = self.role.description
        entity_description = (
            " for entities " + ", ".join(repr(item) for item in selected_entity_ids)
            if selected_entity_ids
            else ""
        )
        if not candidates:
            raise ResourceBindingError(
                "module_resource_route_not_found",
                f"no route satisfies resource port {self.port_id} with "
                f"{role_description}{entity_description}",
            )
        if len(candidates) > 1:
            candidate_names = ", ".join(
                f"{route.id} ({route.instrument_id})" for route in candidates
            )
            raise ResourceBindingError(
                "module_resource_route_ambiguous",
                f"resource port {self.port_id} with {role_description}"
                f"{entity_description} matches multiple routes: {candidate_names}",
            )
        route = next(iter(candidates))
        return ResourceBinding(
            port_id=self.port_id,
            requested_role=self.role,
            route_id=route.id,
            route_role_id=route.role_id,
            instrument_id=route.instrument_id,
            endpoints=_selected_endpoints(
                route,
                interfaces=self.interfaces,
                entity_ids=selected_entity_ids,
            ),
            entity_ids=selected_entity_ids,
            channel_bindings=_channel_bindings(
                route,
                interfaces=self.interfaces,
                entity_ids=selected_entity_ids,
            ),
        )


class ResourceBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoutingView:
    """Pure projection of accepted configuration into static route manifests."""

    routes: tuple[ResourceRoute, ...] = ()

    @classmethod
    def from_config(cls, config: ConfigProfileSnapshot) -> RoutingView:
        return cls(routes=tuple(config.routing.routes))

    def bind_port(
        self,
        *,
        port_id: LogicalResourcePortId,
        interfaces: Sequence[InterfaceId],
        role: ResourceRoleSelector = DEFAULT_RESOURCE_ROLE,
    ) -> ResourcePortManifest:
        """Freeze complete routes matching the port's structural role."""

        return ResourcePortManifest(
            port_id=port_id,
            role=role,
            interfaces=tuple(interfaces),
            routes=tuple(route for route in self.routes if _role_matches(route, role)),
        )


def _role_matches(route: ResourceRoute, role: ResourceRoleSelector) -> bool:
    if role.kind == "any":
        return True
    if role.kind == "default":
        return route.role_id is None
    return route.role_id == role.role_id


def _route_satisfies(
    route: ResourceRoute,
    *,
    interfaces: tuple[InterfaceId, ...],
    entity_ids: tuple[str, ...],
) -> bool:
    if not entity_ids:
        declared_interfaces = {endpoint.interface_id for endpoint in route.endpoints}
        return all(interface in declared_interfaces for interface in interfaces)
    if not interfaces:
        return all(entity_id in route.entity_ids for entity_id in entity_ids)
    if any(entity_id not in route.entity_ids for entity_id in entity_ids):
        return False
    return all(
        any(
            endpoint.interface_id == interface
            and endpoint.entity_id in (None, entity_id)
            for endpoint in route.endpoints
        )
        for interface in interfaces
        for entity_id in entity_ids
    )


def _channel_bindings(
    route: ResourceRoute,
    *,
    interfaces: tuple[InterfaceId, ...],
    entity_ids: tuple[str, ...],
) -> tuple[CommandChannelBinding, ...]:
    selected_entity_ids = entity_ids or tuple(route.entity_ids)
    return tuple(
        CommandChannelBinding(
            entity_id=entity_id,
            channel_id=endpoint.channel_id,
            interface_id=endpoint.interface_id,
        )
        for entity_id in selected_entity_ids
        for endpoint in route.endpoints
        if endpoint.channel_id is not None
        and (not interfaces or endpoint.interface_id in interfaces)
        and entity_id in endpoint_entity_ids(route, endpoint)
    )


def endpoint_entity_ids(
    route: ResourceRoute,
    endpoint: RoutingEndpoint,
) -> tuple[str, ...]:
    """Project one endpoint onto its logical consumers within the route."""

    if endpoint.entity_id is not None:
        return (endpoint.entity_id,)
    return tuple(route.entity_ids)


def _selected_endpoints(
    route: ResourceRoute,
    *,
    interfaces: tuple[InterfaceId, ...],
    entity_ids: tuple[str, ...],
) -> tuple[RoutingEndpoint, ...]:
    selected_entity_ids = set(entity_ids)
    return tuple(
        endpoint
        for endpoint in route.endpoints
        if (not interfaces or endpoint.interface_id in interfaces)
        and (
            not selected_entity_ids
            or endpoint.entity_id is None
            or endpoint.entity_id in selected_entity_ids
        )
    )
