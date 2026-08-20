"""Durable instrument member observations and settings."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.instrument_members import (
    DevicePropertyRef,
    DeviceSchemaId,
    PropertyRef,
    StateMemberRef,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import StateValue
from scopecat.records.measurement import MeasurementAcquisitionValue
from scopecat.records.metadata import JsonMetadata

type _NonEmptyId = Annotated[str, Field(min_length=1)]
type StateMemberIdentity = tuple[str, str, tuple[str, ...], str]
type ObservationSource = Literal[
    "hardware_query",
    "command_confirmed",
    "configured_fixed",
]


class CommandChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: _NonEmptyId
    channel_id: _NonEmptyId
    interface_id: InterfaceId | None = None


def validate_entity_target(
    entity_ids: Sequence[str],
    channel_bindings: Sequence[CommandChannelBinding],
) -> None:
    if any(not entity_id for entity_id in entity_ids):
        msg = "entity target ids must be non-empty"
        raise ValueError(msg)
    if len(entity_ids) != len(set(entity_ids)):
        msg = "entity target ids must be unique"
        raise ValueError(msg)
    unbound = sorted(
        {
            binding.entity_id
            for binding in channel_bindings
            if binding.entity_id not in entity_ids
        }
    )
    if unbound:
        msg = "channel bindings reference entities outside the target: " + ", ".join(
            unbound
        )
        raise ValueError(msg)


class InterfaceStateMemberTarget(BaseModel):
    """One member of a portable interface at a physical component path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["interface"] = "interface"
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    property_id: _NonEmptyId


class DeviceStateMemberTarget(BaseModel):
    """One model-specific member not promoted to a portable interface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["device"] = "device"
    schema_id: DeviceSchemaId
    component_path: tuple[_NonEmptyId, ...] = ()
    property_id: _NonEmptyId


type StateMemberTarget = Annotated[
    InterfaceStateMemberTarget | DeviceStateMemberTarget,
    Field(discriminator="kind"),
]


def state_member_target(reference: StateMemberRef) -> StateMemberTarget:
    if isinstance(reference, PropertyRef):
        return InterfaceStateMemberTarget(
            interface_id=reference.interface_id,
            component_path=reference.component_path,
            property_id=reference.property_id,
        )
    return DeviceStateMemberTarget(
        schema_id=reference.schema_id,
        component_path=reference.component_path,
        property_id=reference.property_id,
    )


def state_member_ref(target: StateMemberTarget) -> StateMemberRef:
    if isinstance(target, InterfaceStateMemberTarget):
        return PropertyRef(
            target.interface_id,
            target.component_path,
            target.property_id,
        )
    return DevicePropertyRef(
        target.schema_id,
        target.component_path,
        target.property_id,
    )


def state_member_identity(
    target: StateMemberTarget | StateMemberRef,
) -> StateMemberIdentity:
    resolved = (
        target
        if isinstance(target, (InterfaceStateMemberTarget, DeviceStateMemberTarget))
        else state_member_target(target)
    )
    if isinstance(resolved, InterfaceStateMemberTarget):
        return (
            "interface",
            resolved.interface_id,
            resolved.component_path,
            resolved.property_id,
        )
    return (
        "device",
        resolved.schema_id,
        resolved.component_path,
        resolved.property_id,
    )


def state_member_sort_key(identity: StateMemberIdentity) -> str:
    return repr(identity)


class InstrumentStateSetting(BaseModel):
    """One desired member value used by configuration or a state command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: StateMemberTarget
    value: StateValue


class InstrumentStateObservation(BaseModel):
    """One independently obtained physical member value."""

    model_config = ConfigDict(extra="forbid")

    target: StateMemberTarget
    value: StateValue
    source: ObservationSource = "hardware_query"
    observed_at: datetime | None = None
    coherence_id: str | None = None
    entity_ids: tuple[_NonEmptyId, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateObservation:
        validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


def state_setting(
    target: StateMemberRef,
    value: StateValue,
) -> InstrumentStateSetting:
    """Build a durable desired value from a driver-facing member reference."""

    return InstrumentStateSetting(target=state_member_target(target), value=value)


def state_observation(
    target: StateMemberRef,
    value: StateValue,
    *,
    source: ObservationSource = "hardware_query",
    observed_at: datetime | None = None,
    coherence_id: str | None = None,
    entity_ids: tuple[str, ...] = (),
    channel_bindings: tuple[CommandChannelBinding, ...] = (),
) -> InstrumentStateObservation:
    """Build one durable observation from a driver-facing member reference."""

    return InstrumentStateObservation(
        target=state_member_target(target),
        value=value,
        source=source,
        observed_at=observed_at,
        coherence_id=coherence_id,
        entity_ids=entity_ids,
        channel_bindings=channel_bindings,
    )


class InstrumentStateSnapshot(BaseModel):
    """A durable capture assembled from independent member observations.

    A snapshot is evidence at a lifecycle boundary or an API projection. It is
    not the driver query unit and is complete only relative to an explicit
    capture plan.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    observations: list[InstrumentStateObservation] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> InstrumentStateSnapshot:
        identities = [
            state_member_identity(observation.target)
            for observation in self.observations
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument state snapshot member targets must be unique"
            raise ValueError(msg)
        return self


class InstrumentStateReadback(BaseModel):
    """Fresh observations returned for one explicit member read request."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    observations: list[InstrumentStateObservation] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)


class InstrumentReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, MeasurementAcquisitionValue] = Field(default_factory=dict)
    metadata: JsonMetadata = Field(default_factory=dict)


__all__ = [
    "CommandChannelBinding",
    "DeviceStateMemberTarget",
    "InstrumentReadback",
    "InstrumentStateObservation",
    "InstrumentStateReadback",
    "InstrumentStateSetting",
    "InstrumentStateSnapshot",
    "InterfaceStateMemberTarget",
    "ObservationSource",
    "StateMemberIdentity",
    "StateMemberTarget",
    "state_member_identity",
    "state_member_ref",
    "state_member_sort_key",
    "state_member_target",
    "state_observation",
    "state_setting",
    "validate_entity_target",
]
