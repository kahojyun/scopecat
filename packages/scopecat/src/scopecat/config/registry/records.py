"""Durable records owned by the configuration registry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Self, override

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.config import ConfigContentHash
from scopecat.records.run import utc_now

CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION = "scopecat.config.registry_entry.v6"
CONFIG_REGISTRY_INDEX_SCHEMA_VERSION = "scopecat.config.registry_index.v2"
CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION = "scopecat.config.registry_active_state.v2"
CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION = (
    "scopecat.config.registry_activation_record.v2"
)

type EvidenceContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]


class _FrozenValidatedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @override
    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


class DirectConfigRegistrySource(_FrozenValidatedModel):
    kind: Literal["direct_config_profile"] = "direct_config_profile"


class CandidateProposalRegistryEvidence(_FrozenValidatedModel):
    proposal_id: str
    proposal_record_content_hash: EvidenceContentHash
    approval_event_id: str
    approval_record_content_hash: EvidenceContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> CandidateProposalRegistryEvidence:
        if not self.proposal_id or not self.approval_event_id:
            msg = "candidate proposal evidence identity fields must be non-empty"
            raise ValueError(msg)
        return self


class CandidateConfigRegistrySource(_FrozenValidatedModel):
    kind: Literal["candidate_config"] = "candidate_config"
    run_id: str
    proposal_evidence: tuple[CandidateProposalRegistryEvidence, ...] = Field(
        min_length=1
    )
    base_config_content_hash: ConfigContentHash

    @model_validator(mode="after")
    def validate_evidence(self) -> CandidateConfigRegistrySource:
        proposal_ids = [evidence.proposal_id for evidence in self.proposal_evidence]
        if len(set(proposal_ids)) != len(proposal_ids):
            msg = "candidate registry source proposal evidence must be unique"
            raise ValueError(msg)
        if not self.run_id:
            msg = "candidate registry source identity fields must be non-empty"
            raise ValueError(msg)
        return self

    @property
    def proposal_ids(self) -> list[str]:
        return [evidence.proposal_id for evidence in self.proposal_evidence]


ConfigRegistryEntrySource = Annotated[
    DirectConfigRegistrySource | CandidateConfigRegistrySource,
    Field(discriminator="kind"),
]


class ConfigRegistryEntry(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config.registry_entry.v6"] = (
        CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION
    )
    id: str
    config_ref: str
    content_hash: ConfigContentHash
    status: Literal["registered"] = "registered"
    source: ConfigRegistryEntrySource
    registered_by: str
    note: str = ""
    registered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryEntry:
        if not self.id or not self.config_ref or not self.registered_by.strip():
            msg = "config registry entry identity fields must be non-empty"
            raise ValueError(msg)
        return self


class ConfigRegistryIndex(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config.registry_index.v2"] = (
        CONFIG_REGISTRY_INDEX_SCHEMA_VERSION
    )
    entries: tuple[ConfigRegistryEntry, ...] = Field(default_factory=tuple)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_entries(self) -> ConfigRegistryIndex:
        entry_ids = [entry.id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            msg = "config registry index entry ids must be unique"
            raise ValueError(msg)
        return self


class ConfigRegistryActivationRecord(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config.registry_activation_record.v2"] = (
        CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION
    )
    id: str
    generation: int = Field(ge=1)
    action: Literal["activation", "rollback"]
    entry_id: str
    entry_content_hash: ConfigContentHash
    previous_entry_id: str | None = None
    previous_entry_content_hash: ConfigContentHash | None = None
    operator: str
    note: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryActivationRecord:
        if not self.id or not self.entry_id or not self.operator.strip():
            msg = "config registry activation identity fields must be non-empty"
            raise ValueError(msg)
        if (self.previous_entry_id is None) != (
            self.previous_entry_content_hash is None
        ):
            msg = "previous registry entry id and content hash must be paired"
            raise ValueError(msg)
        return self


class ConfigRegistryActiveState(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config.registry_active_state.v2"] = (
        CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION
    )
    generation: int = Field(ge=1)
    active_entry_id: str
    active_entry_content_hash: ConfigContentHash
    history: tuple[ConfigRegistryActivationRecord, ...] = Field(default_factory=tuple)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_history_head(self) -> ConfigRegistryActiveState:
        if not self.active_entry_id:
            msg = "config registry active entry id must be non-empty"
            raise ValueError(msg)
        if not self.history:
            msg = "config registry active state requires activation history"
            raise ValueError(msg)
        latest = self.history[-1]
        if latest.generation != self.generation:
            msg = "active generation does not match activation history"
            raise ValueError(msg)
        if latest.entry_id != self.active_entry_id:
            msg = "active entry does not match activation history"
            raise ValueError(msg)
        if latest.entry_content_hash != self.active_entry_content_hash:
            msg = "active content hash does not match activation history"
            raise ValueError(msg)
        if len(self.history) != self.generation or any(
            record.generation != index
            for index, record in enumerate(self.history, start=1)
        ):
            msg = "activation history generations must be contiguous"
            raise ValueError(msg)
        record_ids = [record.id for record in self.history]
        if len(set(record_ids)) != len(record_ids):
            msg = "activation history record ids must be unique"
            raise ValueError(msg)
        first = self.history[0]
        if (
            first.previous_entry_id is not None
            or first.previous_entry_content_hash is not None
        ):
            msg = "initial activation must not have a previous entry"
            raise ValueError(msg)
        for previous, current in zip(self.history, self.history[1:], strict=False):
            if (
                current.previous_entry_id != previous.entry_id
                or current.previous_entry_content_hash != previous.entry_content_hash
            ):
                msg = "activation history entry chain is inconsistent"
                raise ValueError(msg)
        return self


__all__ = [
    "CandidateConfigRegistrySource",
    "CandidateProposalRegistryEvidence",
    "ConfigRegistryActivationRecord",
    "ConfigRegistryActiveState",
    "ConfigRegistryEntry",
    "ConfigRegistryEntrySource",
    "ConfigRegistryIndex",
    "DirectConfigRegistrySource",
    "EvidenceContentHash",
]
