"""Static physical resource manifests over accepted configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
)
from scopecat.records.instrument import CommandChannelBinding


@dataclass(frozen=True)
class ResourceBinding:
    """One instrument shard selected for a logical resource port."""

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
        """Select the single driver invocation for an action or acquisition.

        Different points may select different instruments, but one point-local
        action or acquisition is atomic at one driver and is never implicitly
        broadcast across instrument shards.
        """

        shards = self.select_shards(entity_ids)
        if len(shards) > 1:
            raise ResourceBindingError(
                "module_resource_port_ambiguous",
                f"resource port {self.port_id} spans multiple instruments: "
                + ", ".join(shard.instrument_id for shard in shards),
            )
        if not shards:
            raise AssertionError("successful resource selection lost its shard")
        return next(iter(shards))

    def select_shards(
        self,
        entity_ids: Sequence[str] = (),
    ) -> tuple[ResourceBinding, ...]:
        """Project selected entities onto their static instrument owners.

        This split is intended for desired state, where different devices may
        maintain their explicit values through different drivers. It does not
        turn a multi-instrument action or acquisition into a broadcast.
        """

        selected_entity_ids = tuple(dict.fromkeys(entity_ids))
        if selected_entity_ids:
            entities_by_instrument: dict[str, list[str]] = {}
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
                instrument_id = next(iter(candidates))
                entities_by_instrument.setdefault(instrument_id, []).append(entity_id)
            return tuple(
                self._resource_binding(
                    instrument_id,
                    entity_ids=tuple(shard_entity_ids),
                )
                for instrument_id, shard_entity_ids in entities_by_instrument.items()
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
        return (
            self._resource_binding(
                next(iter(self.default_instrument_ids)),
                entity_ids=(),
            ),
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
    channel_lines_by_id: dict[str, str | None] | None = None
    channel_groups_by_id: dict[str, tuple[str, ...]] | None = None

    @classmethod
    def from_config(cls, config: ConfigProfileSnapshot) -> RoutingView:
        bindings = tuple(config.routing.bindings)
        return cls(
            bindings=bindings,
            channel_lines_by_id={
                channel.id: channel.line_id for channel in config.topology.channels
            },
            channel_groups_by_id={
                channel.id: tuple(channel.group_ids)
                for channel in config.topology.channels
            },
        )

    def bind_port(
        self,
        *,
        port_id: LogicalResourcePortId,
        capabilities: Sequence[str],
    ) -> ResourcePortManifest:
        """Freeze candidates satisfying the port's complete capability contract.

        Every selected entity must have every capability required by the logical
        port on the same candidate instrument; partial capability matches are
        deliberately excluded.
        """

        selected_capabilities = tuple(capabilities)
        instrument_ids = tuple(
            dict.fromkeys(binding.instrument_id for binding in self.bindings)
        )
        default_instrument_ids = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if self._instrument_satisfies(
                instrument_id,
                capabilities=selected_capabilities,
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
                            capabilities=selected_capabilities,
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
                        capabilities=selected_capabilities,
                    )
                    for instrument_id in instrument_ids
                }
            ),
        )

    def _instrument_satisfies(
        self,
        instrument_id: str,
        *,
        capabilities: tuple[str, ...],
        entity_ids: tuple[str, ...],
    ) -> bool:
        instrument_bindings = self._bindings_for_instrument(instrument_id)
        declared_capabilities = {binding.capability for binding in instrument_bindings}
        if not all(capability in declared_capabilities for capability in capabilities):
            return False
        if not entity_ids:
            return True
        if not capabilities:
            served_entity_ids = {
                binding.entity_id
                for binding in instrument_bindings
                if binding.entity_id is not None
            }
            return all(entity_id in served_entity_ids for entity_id in entity_ids)
        return all(
            any(
                binding.capability == capability and binding.entity_id == entity_id
                for binding in instrument_bindings
            )
            for capability in capabilities
            for entity_id in entity_ids
        )

    def _channel_bindings(
        self,
        instrument_id: str,
        *,
        capabilities: tuple[str, ...],
    ) -> tuple[CommandChannelBinding, ...]:
        selected: list[CommandChannelBinding] = []
        for endpoint in self._bindings_for_instrument(instrument_id):
            if endpoint.entity_id is None or endpoint.channel_id is None:
                continue
            if capabilities and endpoint.capability not in capabilities:
                continue
            selected.append(
                self._enriched_binding(
                    CommandChannelBinding(
                        entity_id=endpoint.entity_id,
                        channel_id=endpoint.channel_id,
                        capability=endpoint.capability,
                        metadata=endpoint.metadata,
                    )
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

    def _enriched_binding(
        self,
        binding: CommandChannelBinding,
    ) -> CommandChannelBinding:
        channel_line = self._channel_line(binding.channel_id)
        channel_groups = self._channel_groups(binding.channel_id)
        has_inferred_topology = channel_line is not None or bool(channel_groups)
        if not has_inferred_topology:
            return binding
        return binding.model_copy(
            update={
                "line_id": channel_line,
                "group_ids": list(channel_groups),
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
