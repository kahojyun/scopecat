"""Durable instrument state and readback records shared with SDK contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.state import StateValue
from scopecat.records._metadata import JsonMetadata
from scopecat.records.measurement import MeasurementValue

type _NonEmptyId = Annotated[str, Field(min_length=1)]
type StateTargetIdentity = tuple[
    str,
    str,
    tuple[str, ...],
    tuple[tuple[str, str, str | None], ...],
]


class CommandChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: _NonEmptyId
    channel_id: _NonEmptyId
    capability: _NonEmptyId | None = None


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


def state_target_identity(
    capability_id: str,
    field_path: str,
    entity_ids: Sequence[str],
    channel_bindings: Sequence[CommandChannelBinding],
) -> StateTargetIdentity:
    return (
        capability_id,
        field_path,
        tuple(entity_ids),
        tuple(
            (
                binding.entity_id,
                binding.channel_id,
                binding.capability,
            )
            for binding in channel_bindings
        ),
    )


def state_target_sort_key(identity: StateTargetIdentity) -> str:
    return repr(identity)


class InstrumentStateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: list[_NonEmptyId] = Field(default_factory=list)
    channel_bindings: list[CommandChannelBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> InstrumentStateField:
        validate_entity_target(self.entity_ids, self.channel_bindings)
        return self


class InstrumentStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    fields: list[InstrumentStateField] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> InstrumentStateSnapshot:
        identities = [
            state_target_identity(
                field.capability_id,
                field.field_path,
                field.entity_ids,
                field.channel_bindings,
            )
            for field in self.fields
        ]
        if len(identities) != len(set(identities)):
            msg = "instrument state snapshot field targets must be unique"
            raise ValueError(msg)
        return self


class InstrumentReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, MeasurementValue] = Field(default_factory=dict)
    metadata: JsonMetadata = Field(default_factory=dict)
