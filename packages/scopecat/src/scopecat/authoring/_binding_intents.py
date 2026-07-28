"""Source-only resource and desired-state binding intents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from scopecat.authoring._value_refs import ValueRef
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.interface_identity import InterfaceId, require_interface_id
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)

type EntitySource = ValueRef
type BindingValue = (
    ValueRef | Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)


@dataclass(frozen=True)
class ResourceSelector:
    interfaces: tuple[InterfaceId, ...] = ()
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
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    property_id: str
    value: BindingValue


ExperimentBindingIntent = BindingIntent


def requires(
    *interfaces: InterfaceId,
    for_entities: Sequence[EntitySource] = (),
) -> ResourceSelector:
    return ResourceSelector(
        interfaces=tuple(require_interface_id(item) for item in interfaces),
        entity_inputs=tuple(for_entities),
    )


def resource_port(
    id: str,
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


def bind_property(
    port_id: str,
    *,
    interface: InterfaceId,
    property: str,
    component_path: Sequence[str] = (),
    value: BindingValue,
) -> BindingIntent:
    """Build a property binding with explicit interface and component identity."""

    selected_component_path = tuple(component_path)
    if (
        not port_id
        or not property
        or any(not component for component in selected_component_path)
    ):
        msg = "binding port, component, and property ids must be non-empty"
        raise ValueError(msg)
    return BindingIntent(
        port_id=logical_resource_port_id(port_id),
        interface_id=require_interface_id(interface),
        component_path=selected_component_path,
        property_id=property,
        value=value,
    )
