"""Durable records owned by the configuration registry."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.run_outcome import utc_now
from scopecat.records.config import ConfigContentHash


class _FrozenRegistryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class DirectConfigRegistrySource(_FrozenRegistryModel):
    kind: Literal["direct_config_profile"] = "direct_config_profile"


class ManualConfigDraftRegistrySource(_FrozenRegistryModel):
    """Provenance for typed parameter edits derived from an active entry."""

    kind: Literal["manual_parameter_updates"] = "manual_parameter_updates"
    base_entry_id: str
    base_config_content_hash: ConfigContentHash
    base_registry_generation: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_identity(self) -> ManualConfigDraftRegistrySource:
        if not self.base_entry_id:
            raise ValueError("manual config draft base entry id must be non-empty")
        return self


class CandidateConfigRegistrySource(_FrozenRegistryModel):
    kind: Literal["candidate_config"] = "candidate_config"
    run_id: str
    proposal_id: str
    approval_record_id: str
    base_config_content_hash: ConfigContentHash

    @model_validator(mode="after")
    def validate_evidence(self) -> CandidateConfigRegistrySource:
        if not self.run_id or not self.proposal_id or not self.approval_record_id:
            msg = "candidate registry source identity fields must be non-empty"
            raise ValueError(msg)
        return self


ConfigRegistryEntrySource = Annotated[
    DirectConfigRegistrySource
    | ManualConfigDraftRegistrySource
    | CandidateConfigRegistrySource,
    Field(discriminator="kind"),
]


class ConfigRegistryEntry(_FrozenRegistryModel):
    id: str
    config_ref: str
    content_hash: ConfigContentHash
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


class ConfigRegistryActivationRecord(_FrozenRegistryModel):
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


class ConfigRegistryActiveState(_FrozenRegistryModel):
    generation: int = Field(ge=1)
    active_entry_id: str
    active_entry_content_hash: ConfigContentHash
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryActiveState:
        if not self.active_entry_id:
            msg = "config registry active entry id must be non-empty"
            raise ValueError(msg)
        return self
