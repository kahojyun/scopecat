"""Source-only resource and desired-state binding intents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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


@dataclass(frozen=True)
class BindingIntent:
    port_path: str
    value: BindingValue


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


def bind(
    port_path: str,
    value: BindingValue,
) -> BindingIntent:
    return BindingIntent(port_path=port_path, value=value)


__all__ = [
    "BindingIntent",
    "BindingValue",
    "EntitySource",
    "ExperimentBindingIntent",
    "ResourcePort",
    "ResourceSelector",
    "bind",
    "requires",
    "resource_port",
]
