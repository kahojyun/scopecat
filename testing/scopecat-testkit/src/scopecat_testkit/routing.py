from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.records.config import (
    ConfigProfileSnapshot,
    ResourceRoleSpec,
    ResourceRoute,
    RoutingEndpoint,
    RoutingGraph,
)

from scopecat_testkit.authoring import load_config


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


def routing_config(
    *,
    instruments: Mapping[str, str],
    bindings: Sequence[RoutingEndpointSpec],
    extra_entities: Sequence[EntityRef] = (),
) -> ConfigProfileSnapshot:
    """Build a test config with explicit instruments, entities, and routes."""

    seed = load_config()
    seed_instrument = seed.instrument_registry.instruments[0]
    known_entity_ids = {entity.id for entity in seed.topology.entities}
    selected_entities = [
        entity for entity in extra_entities if entity.id not in known_entity_ids
    ]
    system = seed.system.model_copy(
        update={
            "topology": seed.topology.model_copy(
                update={
                    "entities": [*seed.topology.entities, *selected_entities],
                }
            ),
            "instrument_registry": seed.instrument_registry.model_copy(
                update={
                    "instruments": [
                        seed_instrument.model_copy(
                            update={
                                "id": instrument_id,
                                "exclusivity_key": instrument_id,
                                "kind": kind,
                            }
                        )
                        for instrument_id, kind in instruments.items()
                    ]
                }
            ),
            "routing": routing_graph(bindings=bindings),
        }
    )
    return seed.model_copy(update={"system": system})
