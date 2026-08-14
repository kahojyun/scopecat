"""Domain values exchanged with an instrument implementation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import JsonValue

from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import CommandChannelBinding
from scopecat.records.measurement import MeasurementAcquisitionValue
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.problems import Problem

type DriverScalar = bool | int | float | str | Quantity


@dataclass(frozen=True, slots=True)
class DriverStateEntry:
    """One physical state slot addressed by ``target.component_path``.

    Entity ids and channel bindings preserve demand and route provenance. They
    do not select a second state slot or replace physical component dispatch.
    """

    target: PropertyRef
    value: DriverScalar
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverState:
    values: Mapping[PropertyRef, DriverScalar] = field(
        default_factory=lambda: dict[PropertyRef, DriverScalar]()
    )
    scoped_values: tuple[DriverStateEntry, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @property
    def entries(self) -> tuple[DriverStateEntry, ...]:
        return (
            *(
                DriverStateEntry(target=target, value=value)
                for target, value in self.values.items()
            ),
            *self.scoped_values,
        )


@dataclass(frozen=True, slots=True)
class DriverStatePatch:
    values: Mapping[PropertyRef, DriverScalar] = field(
        default_factory=lambda: dict[PropertyRef, DriverScalar]()
    )
    scoped_values: tuple[DriverStateEntry, ...] = ()

    @property
    def entries(self) -> tuple[DriverStateEntry, ...]:
        return (
            *(
                DriverStateEntry(target=target, value=value)
                for target, value in self.values.items()
            ),
            *self.scoped_values,
        )


@dataclass(frozen=True, slots=True)
class DriverPayload:
    """One opaque operation payload decoded before implementation dispatch."""

    schema_id: str
    value: object = field(repr=False)


type DriverArgument = DriverScalar | DriverPayload


@dataclass(frozen=True, slots=True)
class DriverOperation:
    """One operation dispatched to the physical path in ``target``.

    Entity ids and channel bindings are provenance for the resolved logical
    resource; implementations must not use their cardinality as target identity.
    """

    target: OperationRef
    arguments: Mapping[str, DriverArgument] = field(
        default_factory=lambda: dict[str, DriverArgument]()
    )
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverAcquisition:
    """One acquisition dispatched to the physical path in ``target``.

    Channel bindings describe the route that produced this request. The target
    path remains the driver's authoritative physical dispatch key.
    """

    target: AcquisitionRef
    results: frozenset[AcquisitionResultRef]
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverReadback:
    values: Mapping[AcquisitionResultRef, MeasurementAcquisitionValue]
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DriverSuccess[T]:
    value: T
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DriverRejected:
    problems: tuple[Problem, ...]
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DriverUnknown:
    problems: tuple[Problem, ...]
    metadata: dict[str, JsonValue] = field(default_factory=dict)


type DriverOutcome[T] = DriverSuccess[T] | DriverRejected | DriverUnknown


__all__ = [
    "DriverAcquisition",
    "DriverArgument",
    "DriverOperation",
    "DriverOutcome",
    "DriverPayload",
    "DriverReadback",
    "DriverRejected",
    "DriverScalar",
    "DriverState",
    "DriverStateEntry",
    "DriverStatePatch",
    "DriverSuccess",
    "DriverUnknown",
]
