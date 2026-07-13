"""Source-only resource and desired-state binding intents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from scopecat._qualified_name import qualified_name
from scopecat.authoring._value_refs import ValueRef
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

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
    id: str
    selector: ResourceSelector
    scope: tuple[str, ...] = ()

    @property
    def qualified_id(self) -> str:
        return qualified_name(self.scope, self.id)


@dataclass(frozen=True)
class BindingIntent:
    port_id: str
    capability_id: str
    field_path: str
    value: BindingValue

    @property
    def port_path(self) -> str:
        """Human-readable projection; compilation uses the structured fields."""

        return f"{self.port_id}.{self.capability_id}.{self.field_path}"


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
    return ResourcePort(id=id, selector=selector)


def prefix_resource_port(
    port: ResourcePort,
    *scope: str,
) -> ResourcePort:
    """Prefix one logical resource requirement with an instance scope."""

    if not scope:
        return port
    return replace(port, scope=(*scope, *port.scope))


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
        port_id=port_id,
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
