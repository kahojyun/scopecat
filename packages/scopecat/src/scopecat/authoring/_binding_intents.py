"""Source-only resource and desired-state binding intents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from scopecat.authoring._value_refs import ValueRef
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type EntitySource = ValueRef
type BindingValue = (
    ValueRef | Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)


@dataclass(frozen=True)
class ResourceSelector:
    capabilities: tuple[str, ...] = ()
    entity_inputs: tuple[EntitySource, ...] = ()


@dataclass(frozen=True)
class ResourcePort:
    symbol_id: LogicalResourcePortId
    selector: ResourceSelector

    @property
    def id(self) -> str:
        return self.symbol_id.local_id

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol_id.scope

    @property
    def qualified_id(self) -> str:
        return self.symbol_id.qualified_name


@dataclass(frozen=True)
class BindingIntent:
    port_id: LogicalResourcePortId
    capability_id: str
    field_path: str
    value: BindingValue

    @property
    def port_path(self) -> str:
        """Human-readable projection; compilation uses the structured fields."""

        return f"{self.port_id.qualified_name}.{self.capability_id}.{self.field_path}"


ExperimentBindingIntent = BindingIntent


def requires(
    *capabilities: str,
    for_entities: Sequence[EntitySource] = (),
) -> ResourceSelector:
    return ResourceSelector(
        capabilities=tuple(capabilities),
        entity_inputs=tuple(for_entities),
    )


def resource_port(
    id: str,  # noqa: A002
    selector: ResourceSelector,
) -> ResourcePort:
    return ResourcePort(symbol_id=logical_resource_port_id(id), selector=selector)


def prefix_resource_port(
    port: ResourcePort,
    *scope: str,
) -> ResourcePort:
    """Prefix one logical resource requirement with an instance scope."""

    if not scope:
        return port
    return replace(port, symbol_id=port.symbol_id.prefixed(*scope))


def bind_field(
    port_id: str,
    *,
    capability: str,
    field: str,
    value: BindingValue,
) -> BindingIntent:
    """Build a binding without encoding its resource identity into a path."""

    if not port_id or not capability or not field:
        msg = "binding port, capability, and field ids must be non-empty"
        raise ValueError(msg)
    return BindingIntent(
        port_id=logical_resource_port_id(port_id),
        capability_id=capability,
        field_path=field,
        value=value,
    )


__all__ = [
    "BindingIntent",
    "BindingValue",
    "EntitySource",
    "ExperimentBindingIntent",
    "ResourcePort",
    "ResourceSelector",
    "bind_field",
    "prefix_resource_port",
    "requires",
    "resource_port",
]
