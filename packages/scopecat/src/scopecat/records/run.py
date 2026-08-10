"""Accepted run snapshots and terminal outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from scopecat.kernel.frozen import freeze_json_mapping, thaw_json_value
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.run_outcome import RunOutcome, RunStatus, utc_now
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigContentHash

type RunSequenceProposalId = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
type RunSequenceRequestHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]


class ConfigRegistryRunConfigSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["config_registry"] = "config_registry"
    selector: str
    entry_id: str
    config_ref: str
    content_hash: ConfigContentHash
    registry_generation: int | None = Field(default=None, ge=1)


class AnalysisCandidateRunConfigSource(BaseModel):
    """Analysis candidate resolved for one run without becoming the default."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["analysis_candidate"] = "analysis_candidate"
    source_run_id: str
    analysis_record_id: str
    proposal_id: str
    base_config_content_hash: ConfigContentHash
    content_hash: ConfigContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> AnalysisCandidateRunConfigSource:
        if (
            not self.source_run_id
            or not self.analysis_record_id
            or not self.proposal_id
        ):
            raise ValueError("analysis candidate run source identity must be non-empty")
        return self


type RunConfigSource = Annotated[
    ConfigRegistryRunConfigSource | AnalysisCandidateRunConfigSource,
    Field(discriminator="kind"),
]


class RunSequenceTransition(BaseModel):
    """Durable transition owned by the completed run it evaluated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_id: str = Field(min_length=1)
    run_index: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    based_on_run_id: str = Field(min_length=1)
    status: Literal[
        "proposed",
        "stopped",
        "budget_exhausted",
        "proposal_failed",
    ]
    next_experiment_id: str | None = Field(default=None, min_length=1)
    proposal_id: RunSequenceProposalId | None = None
    next_request_content_hash: RunSequenceRequestHash | None = None
    next_config_content_hash: ConfigContentHash | None = None
    next_config_source: RunConfigSource | None = None
    details: Mapping[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transition(self) -> RunSequenceTransition:
        proposal_fields = (
            self.next_experiment_id,
            self.proposal_id,
            self.next_request_content_hash,
            self.next_config_content_hash,
        )
        if self.status == "proposed" and any(
            field is None for field in proposal_fields
        ):
            raise ValueError(
                "proposed sequence transition requires complete request and config "
                "identity"
            )
        if self.status != "proposed" and (
            any(field is not None for field in proposal_fields)
            or self.next_config_source is not None
        ):
            raise ValueError(
                "non-proposal sequence transitions cannot select a request or config"
            )
        if (
            self.next_config_source is not None
            and self.next_config_source.content_hash != self.next_config_content_hash
        ):
            raise ValueError(
                "sequence proposal config source hash must match its config"
            )
        object.__setattr__(self, "details", freeze_json_mapping(self.details))
        return self

    @field_serializer("details")
    def serialize_details(self, value: Mapping[str, JsonValue]) -> object:
        return thaw_json_value(value)


class RunSequenceLineage(BaseModel):
    """Durable identity of one run within a notebook-driven sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_id: str = Field(min_length=1)
    run_index: int = Field(ge=0)
    max_runs: int = Field(default=10, ge=1)
    previous_run_id: str | None = Field(default=None, min_length=1)
    proposal_id: RunSequenceProposalId | None = None

    @model_validator(mode="after")
    def validate_predecessor(self) -> RunSequenceLineage:
        if self.run_index == 0 and (
            self.previous_run_id is not None or self.proposal_id is not None
        ):
            raise ValueError("the first sequence run cannot have proposal lineage")
        if self.run_index > 0 and (
            self.previous_run_id is None or self.proposal_id is None
        ):
            raise ValueError("a later sequence run requires proposal lineage")
        return self


class RunManifest(BaseModel):
    """Accepted snapshot plus content and an optional terminal outcome."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    outcome: RunOutcome | None = None
    config_content_hash: ConfigContentHash
    config_source: RunConfigSource | None = None
    sequence: RunSequenceLineage | None = None
    contents: tuple[RunContentEntry, ...] = ()

    @property
    def records(self) -> tuple[RunContentEntry, ...]:
        return tuple(entry for entry in self.contents if entry.role == "record")

    @property
    def datasets(self) -> tuple[RunContentEntry, ...]:
        return tuple(entry for entry in self.contents if entry.role == "dataset")

    @property
    def artifacts(self) -> tuple[RunContentEntry, ...]:
        return tuple(entry for entry in self.contents if entry.role == "artifact")

    @model_validator(mode="after")
    def validate_identity(self) -> RunManifest:
        if (
            self.config_source is not None
            and self.config_source.content_hash != self.config_content_hash
        ):
            msg = "run config source hash does not match its accepted snapshot hash"
            raise ValueError(msg)
        if self.outcome is not None and self.outcome.run_id != self.run_id:
            msg = "run outcome run_id does not match its manifest"
            raise ValueError(msg)
        return self

    @property
    def status(self) -> RunStatus:
        """Return a compact display status from the optional outcome."""

        if self.outcome is None:
            return "planned"
        return self.outcome.status
