"""Durable instrument state and readback records shared with SDK contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import StateValue
from scopecat.records._metadata import JsonMetadata
from scopecat.records.measurement import MeasurementValue

type _NonEmptyId = Annotated[str, Field(min_length=1)]
type StateTargetScopeIdentity = tuple[
    str,
    tuple[str, ...],
]
type PropertyTargetIdentity = tuple[
    str,
    tuple[str, ...],
    str,
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


def state_target_scope_identity(
    interface_id: str,
    component_path: Sequence[str],
) -> StateTargetScopeIdentity:
    """Identify one physical instrument-state scope."""

    return (
        interface_id,
        tuple(component_path),
    )


def property_target_identity(
    interface_id: str,
    component_path: Sequence[str],
    property_id: str,
) -> PropertyTargetIdentity:
    scope = state_target_scope_identity(
        interface_id,
        component_path,
    )
    return (
        scope[0],
        scope[1],
        property_id,
    )


def property_target_sort_key(identity: PropertyTargetIdentity) -> str:
    return repr(identity)


class InstrumentPropertyState(BaseModel):
    """One physical persistent-property value."""

    model_config = ConfigDict(extra="forbid")

    interface_id: InterfaceId
    component_path: list[_NonEmptyId] = Field(default_factory=list)
    property_id: _NonEmptyId
    value: StateValue


class InstrumentStateSnapshot(BaseModel):
    """Complete observable persistent state for one physical instrument."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    properties: list[InstrumentPropertyState] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> InstrumentStateSnapshot:
        identities = [
            property_target_identity(
                item.interface_id,
                item.component_path,
                item.property_id,
            )
            for item in self.properties
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument state snapshot property targets must be unique"
            raise ValueError(msg)
        return self


class InstrumentReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, MeasurementValue] = Field(default_factory=dict)
    metadata: JsonMetadata = Field(default_factory=dict)
