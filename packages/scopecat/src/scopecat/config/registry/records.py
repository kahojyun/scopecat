"""Durable records owned by the configuration registry."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.run_outcome import utc_now
from scopecat.records.analysis import ProjectAnalysisDecisionReference
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import Sha256ContentHash

_CONFIG_ACTIVATION_INTENT_CODEC = "scopecat.config-activation-intent.v1"


class _FrozenRegistryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
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


class ManualCandidateAcceptance(_FrozenRegistryModel):
    """Operator-reviewed acceptance without an automated verification run."""

    kind: Literal["manual_review"] = "manual_review"


class CrossRunCandidateAcceptance(_FrozenRegistryModel):
    """Automated acceptance backed by one positive cross-run decision fact."""

    kind: Literal["cross_run_verification"] = "cross_run_verification"
    decision: ProjectAnalysisDecisionReference


CandidateAcceptance = Annotated[
    ManualCandidateAcceptance | CrossRunCandidateAcceptance,
    Field(discriminator="kind"),
]


class CandidateConfigRegistrySource(_FrozenRegistryModel):
    kind: Literal["candidate_config"] = "candidate_config"
    run_id: str
    proposal_id: str
    base_config_content_hash: ConfigContentHash
    acceptance: CandidateAcceptance

    @model_validator(mode="after")
    def validate_evidence(self) -> CandidateConfigRegistrySource:
        if not self.run_id or not self.proposal_id:
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
    actor: str
    note: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryEntry:
        if not self.id or not self.config_ref or not self.actor.strip():
            msg = "config registry entry identity fields must be non-empty"
            raise ValueError(msg)
        return self


class ConfigRegistryActivationRecord(_FrozenRegistryModel):
    generation: int = Field(ge=1)
    action: Literal["activation", "inventory_migration", "undo"]
    entry_id: str
    entry_content_hash: ConfigContentHash
    previous_entry_id: str | None = None
    previous_entry_content_hash: ConfigContentHash | None = None
    actor: str
    note: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryActivationRecord:
        if not self.entry_id or not self.actor.strip():
            msg = "config registry activation identity fields must be non-empty"
            raise ValueError(msg)
        if (self.previous_entry_id is None) != (
            self.previous_entry_content_hash is None
        ):
            msg = "previous registry entry id and content hash must be paired"
            raise ValueError(msg)
        return self


def config_activation_intent_hash(
    *,
    entry_id: str,
    expected_generation: int,
    actor: str,
    note: str = "",
) -> Sha256ContentHash:
    """Identify one exact activate-entry intent independently of its retry key."""

    identity = {
        "codec": _CONFIG_ACTIVATION_INTENT_CODEC,
        "entry_id": entry_id,
        "expected_generation": expected_generation,
        "actor": actor,
        "note": note,
    }
    return f"sha256:{stable_content_hash(identity)}"


class ConfigActivationOperation(_FrozenRegistryModel):
    """Durable result identity for one idempotent activate-entry command."""

    operation_id: str
    intent_hash: Sha256ContentHash
    entry_id: str
    expected_generation: int = Field(ge=0)
    actor: str
    note: str = ""
    activation_generation: int = Field(ge=1)
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigActivationOperation:
        if not self.operation_id or not self.entry_id or not self.actor.strip():
            raise ValueError("config activation operation identity must be non-empty")
        expected_hash = config_activation_intent_hash(
            entry_id=self.entry_id,
            expected_generation=self.expected_generation,
            actor=self.actor,
            note=self.note,
        )
        if self.intent_hash != expected_hash:
            raise ValueError("config activation operation intent hash is inconsistent")
        if self.activation_generation not in {
            self.expected_generation,
            self.expected_generation + 1,
        }:
            raise ValueError(
                "config activation operation generation must be the observed or next "
                "generation"
            )
        return self


class ConfigRegistryEntryPage(_FrozenRegistryModel):
    """Newest-first keyset page of saved configuration revisions."""

    items: tuple[ConfigRegistryEntry, ...] = ()
    next_cursor: int | None = Field(default=None, ge=1)


class ConfigRegistryActivationPage(_FrozenRegistryModel):
    """Newest-first keyset page of default configuration changes."""

    items: tuple[ConfigRegistryActivationRecord, ...] = ()
    next_cursor: int | None = Field(default=None, ge=1)
