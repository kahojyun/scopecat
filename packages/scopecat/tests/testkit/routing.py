from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.records.config import (
    ResourceRoleSpec,
    ResourceRoute,
    RoutingEndpoint,
    RoutingGraph,
)


@dataclass(frozen=True, slots=True)
class RoutingEndpointSpec:
    """Concise test input; ``routing_graph`` closes these into real routes."""

    instrument_id: str
    interface_id: InterfaceId
    entity_id: str | None = None
    channel_id: str | None = None
    component_path: tuple[str, ...] = ()
    role_id: str | None = None


def routing_endpoint(
    *,
    instrument_id: str,
    interface_id: InterfaceId,
    entity_id: str | None = None,
    channel_id: str | None = None,
    component_path: Sequence[str] = (),
    role_id: str | None = None,
) -> RoutingEndpointSpec:
    return RoutingEndpointSpec(
        instrument_id=instrument_id,
        interface_id=interface_id,
        entity_id=entity_id,
        channel_id=channel_id,
        component_path=tuple(component_path),
        role_id=role_id,
    )


def routing_graph(
    *endpoints: RoutingEndpointSpec,
    bindings: Sequence[RoutingEndpointSpec] = (),
) -> RoutingGraph:
    endpoints = (*endpoints, *bindings)
    grouped: dict[tuple[str, str | None], list[RoutingEndpoint]] = {}
    for endpoint in endpoints:
        grouped.setdefault((endpoint.instrument_id, endpoint.role_id), []).append(
            RoutingEndpoint(
                interface_id=endpoint.interface_id,
                entity_id=endpoint.entity_id,
                channel_id=endpoint.channel_id,
                component_path=endpoint.component_path,
            )
        )
    role_ids = tuple(
        dict.fromkeys(
            endpoint.role_id for endpoint in endpoints if endpoint.role_id is not None
        )
    )
    return RoutingGraph(
        roles=[ResourceRoleSpec(id=role_id) for role_id in role_ids],
        routes=[
            ResourceRoute(
                id=instrument_id if role_id is None else f"{instrument_id}.{role_id}",
                instrument_id=instrument_id,
                role_id=role_id,
                entity_ids=list(
                    dict.fromkeys(
                        endpoint.entity_id
                        for endpoint in route_endpoints
                        if endpoint.entity_id is not None
                    )
                ),
                endpoints=route_endpoints,
            )
            for (instrument_id, role_id), route_endpoints in grouped.items()
        ],
    )
