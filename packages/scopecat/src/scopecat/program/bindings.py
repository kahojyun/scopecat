"""Resource declarations and desired-state binding intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from scopecat.kernel.instrument_members import (
    InstrumentCapabilityRef,
    InterfaceRef,
)
from scopecat.kernel.interface_identity import InterfaceId, require_interface_id
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import (
    DEFAULT_RESOURCE_ROLE,
    LogicalResourcePortId,
    ResourceRoleSelector,
    logical_resource_port_id,
)
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.program.state import StateBinding
from scopecat.program.value_refs import ValueRef

type EntitySource = ValueRef
type BindingValue = StateBinding
type InvocationArgumentValue = StateBinding | PayloadValue | None


@dataclass(frozen=True)
class ResourceSelector:
    """Logical capability requirements plus entity and role constraints."""

    capabilities: tuple[InstrumentCapabilityRef, ...] = ()
    entity_inputs: tuple[EntitySource, ...] = ()
    role: ResourceRoleSelector = DEFAULT_RESOURCE_ROLE

    @property
    def interfaces(self) -> tuple[InterfaceId, ...]:
        """Return the interface endpoints needed for physical route selection."""

        return tuple(
            dict.fromkeys(capability.interface_id for capability in self.capabilities)
        )

    def covers(self, capability: InstrumentCapabilityRef) -> bool:
        """Return whether this selector declares an exact capability."""

        return any(
            (
                isinstance(declared, InterfaceRef)
                and declared.interface_id == capability.interface_id
            )
            or declared == capability
            for declared in self.capabilities
        )


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


@dataclass(frozen=True)
class EnsureStateIntent:
    """One coherent desired-state assertion over a logical resource."""

    assignments: tuple[BindingIntent, ...]

    def __post_init__(self) -> None:
        if not self.assignments:
            raise ValueError("desired state requires at least one assignment")


@dataclass(frozen=True)
class InvocationArgumentIntent:
    id: str
    value: InvocationArgumentValue


@dataclass(frozen=True)
class InvocationIntent:
    id: str
    port_id: LogicalResourcePortId
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    operation_id: str
    arguments: tuple[InvocationArgumentIntent, ...]
    scope: tuple[str, ...] = ()


def requires(
    *capabilities: InstrumentCapabilityRef,
    for_entities: Sequence[EntitySource] = (),
    role: ResourceRoleSelector = DEFAULT_RESOURCE_ROLE,
) -> ResourceSelector:
    return ResourceSelector(
        capabilities=tuple(capabilities),
        entity_inputs=tuple(for_entities),
        role=role,
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
    port_id: str | LogicalResourcePortId,
    *,
    interface: InterfaceId,
    property: str,
    component_path: Sequence[str] = (),
    value: BindingValue,
) -> BindingIntent:
    """Build a property binding with explicit interface and component identity."""

    selected_component_path = tuple(component_path)
    selected_port_id = (
        port_id
        if isinstance(port_id, LogicalResourcePortId)
        else logical_resource_port_id(port_id)
    )
    if (
        not selected_port_id.qualified_name
        or not property
        or any(not component for component in selected_component_path)
    ):
        msg = "binding port, component, and property ids must be non-empty"
        raise ValueError(msg)
    if _is_payload_value(value):
        raise TypeError("persistent properties cannot contain opaque payloads")
    return BindingIntent(
        port_id=selected_port_id,
        interface_id=require_interface_id(interface),
        component_path=selected_component_path,
        property_id=property,
        value=value,
    )


def invoke_operation(
    id: str,
    *,
    port_id: str,
    interface: InterfaceId,
    operation: str,
    arguments: Mapping[str, InvocationArgumentValue],
    component_path: Sequence[str] = (),
) -> InvocationIntent:
    """Build one ordered atomic operation invocation."""

    selected_component_path = tuple(component_path)
    if (
        not id
        or not port_id
        or not operation
        or any(not component for component in selected_component_path)
    ):
        raise ValueError(
            "invocation, port, component, and operation ids must be non-empty"
        )
    if any(not argument_id for argument_id in arguments):
        raise ValueError("invocation argument ids must be non-empty")
    return InvocationIntent(
        id=id,
        port_id=logical_resource_port_id(port_id),
        interface_id=require_interface_id(interface),
        component_path=selected_component_path,
        operation_id=operation,
        arguments=tuple(
            InvocationArgumentIntent(argument_id, value)
            for argument_id, value in arguments.items()
        ),
    )


def _is_payload_value(value: object) -> bool:
    return isinstance(value, PayloadValue) or (
        isinstance(value, ValueRef)
        and isinstance(value.value_type, Scalar)
        and isinstance(value.value_type.atom, Payload)
    )
