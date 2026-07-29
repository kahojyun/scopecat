"""Static physical resource manifests over accepted configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
)
from scopecat.records.instrument import CommandChannelBinding


@dataclass(frozen=True)
class ResourceBinding:
    """The one instrument selected for a logical resource port."""

    instrument_id: str
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True)
class ResourcePortManifest:
    """Frozen physical candidates for one logical resource contract.

    Point-local entity values may only select from this manifest. They cannot
    discover providers, construct new physical paths, or change endpoint
    ownership after target preparation.
    """

    port_id: LogicalResourcePortId
    default_instrument_ids: tuple[str, ...]
    instrument_ids_by_entity: Mapping[str, tuple[str, ...]]
    channel_bindings_by_instrument: Mapping[
        str,
        tuple[CommandChannelBinding, ...],
    ]

    def select_one(
        self,
        entity_ids: Sequence[str] = (),
    ) -> ResourceBinding:
        """Select one driver for the complete point-local entity scope."""

        selected_entity_ids = tuple(dict.fromkeys(entity_ids))
        if selected_entity_ids:
            selected_instrument_ids: list[str] = []
            for entity_id in selected_entity_ids:
                candidates = self.instrument_ids_by_entity.get(entity_id, ())
                if not candidates:
                    raise ResourceBindingError(
                        "module_resource_endpoint_not_found",
                        f"no instrument satisfies resource port {self.port_id} for "
                        f"entity {entity_id!r}",
                    )
                if len(candidates) > 1:
                    raise ResourceBindingError(
                        "module_resource_endpoint_ambiguous",
                        f"resource port {self.port_id} entity {entity_id!r} matches "
                        "multiple instruments: " + ", ".join(candidates),
                    )
                selected_instrument_ids.append(next(iter(candidates)))
            instrument_ids = tuple(dict.fromkeys(selected_instrument_ids))
            if len(instrument_ids) > 1:
                raise ResourceBindingError(
                    "module_resource_port_ambiguous",
                    f"resource port {self.port_id} entities span multiple "
                    "instruments: " + ", ".join(instrument_ids),
                )
            return self._resource_binding(
                next(iter(instrument_ids)),
                entity_ids=selected_entity_ids,
            )

        if not self.default_instrument_ids:
            raise ResourceBindingError(
                "module_resource_port_not_found",
                f"no instrument satisfies resource port {self.port_id}",
            )
        if len(self.default_instrument_ids) > 1:
            raise ResourceBindingError(
                "module_resource_port_ambiguous",
                f"resource port {self.port_id} matches multiple instruments: "
                f"{', '.join(self.default_instrument_ids)}",
            )
        return self._resource_binding(
            next(iter(self.default_instrument_ids)),
            entity_ids=(),
        )

    def _resource_binding(
        self,
        instrument_id: str,
        *,
        entity_ids: tuple[str, ...],
    ) -> ResourceBinding:
        channel_bindings = self.channel_bindings_by_instrument.get(instrument_id, ())
        if entity_ids:
            bindings_by_entity: dict[str, list[CommandChannelBinding]] = {}
            for binding in channel_bindings:
                bindings_by_entity.setdefault(binding.entity_id, []).append(binding)
            channel_bindings = tuple(
                binding
                for entity_id in entity_ids
                for binding in bindings_by_entity.get(entity_id, ())
            )
        return ResourceBinding(
            instrument_id=instrument_id,
            entity_ids=entity_ids,
            channel_bindings=channel_bindings,
        )


class ResourceBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoutingView:
    """Pure projection of one accepted configuration into static manifests.

    The view never observes provider state and cannot substitute an endpoint.
    Replacing hardware therefore requires another accepted configuration and
    plan, preserving the physical choice in run provenance.
    """

    bindings: tuple[RoutingEndpointBinding, ...] = ()

    @classmethod
    def from_config(cls, config: ConfigProfileSnapshot) -> RoutingView:
        return cls(bindings=tuple(config.routing.bindings))

    def bind_port(
        self,
        *,
        port_id: LogicalResourcePortId,
        interfaces: Sequence[InterfaceId],
    ) -> ResourcePortManifest:
        """Freeze candidates satisfying the port's complete interface contract.

        Every selected entity must have every interface required by the logical
        port on the same candidate instrument; partial interface matches are
        deliberately excluded.
        """

        selected_interfaces = tuple(interfaces)
        instrument_ids = tuple(
            dict.fromkeys(binding.instrument_id for binding in self.bindings)
        )
        default_instrument_ids = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if self._instrument_satisfies(
                instrument_id,
                interfaces=selected_interfaces,
                entity_ids=(),
            )
        )
        entity_ids = tuple(
            dict.fromkeys(
                binding.entity_id
                for binding in self.bindings
                if binding.entity_id is not None
            )
        )
        return ResourcePortManifest(
            port_id=port_id,
            default_instrument_ids=default_instrument_ids,
            instrument_ids_by_entity=MappingProxyType(
                {
                    entity_id: tuple(
                        instrument_id
                        for instrument_id in instrument_ids
                        if self._instrument_satisfies(
                            instrument_id,
                            interfaces=selected_interfaces,
                            entity_ids=(entity_id,),
                        )
                    )
                    for entity_id in entity_ids
                }
            ),
            channel_bindings_by_instrument=MappingProxyType(
                {
                    instrument_id: self._channel_bindings(
                        instrument_id,
                        interfaces=selected_interfaces,
                    )
                    for instrument_id in instrument_ids
                }
            ),
        )

    def _instrument_satisfies(
        self,
        instrument_id: str,
        *,
        interfaces: tuple[InterfaceId, ...],
        entity_ids: tuple[str, ...],
    ) -> bool:
        instrument_bindings = self._bindings_for_instrument(instrument_id)
        declared_interfaces = {binding.interface_id for binding in instrument_bindings}
        if not all(interface in declared_interfaces for interface in interfaces):
            return False
        if not entity_ids:
            return True
        if not interfaces:
            served_entity_ids = {
                binding.entity_id
                for binding in instrument_bindings
                if binding.entity_id is not None
            }
            return all(entity_id in served_entity_ids for entity_id in entity_ids)
        return all(
            any(
                binding.interface_id == interface and binding.entity_id == entity_id
                for binding in instrument_bindings
            )
            for interface in interfaces
            for entity_id in entity_ids
        )

    def _channel_bindings(
        self,
        instrument_id: str,
        *,
        interfaces: tuple[InterfaceId, ...],
    ) -> tuple[CommandChannelBinding, ...]:
        selected: list[CommandChannelBinding] = []
        for endpoint in self._bindings_for_instrument(instrument_id):
            if endpoint.entity_id is None or endpoint.channel_id is None:
                continue
            if interfaces and endpoint.interface_id not in interfaces:
                continue
            selected.append(
                CommandChannelBinding(
                    entity_id=endpoint.entity_id,
                    channel_id=endpoint.channel_id,
                    interface_id=endpoint.interface_id,
                )
            )
        return tuple(selected)

    def _bindings_for_instrument(
        self,
        instrument_id: str,
    ) -> tuple[RoutingEndpointBinding, ...]:
        return tuple(
            binding
            for binding in self.bindings
            if binding.instrument_id == instrument_id
        )
