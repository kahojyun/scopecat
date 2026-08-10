"""Accepted run snapshots and terminal outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.run_outcome import RunOutcome, RunStatus, utc_now
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigContentHash


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


class RunStageDecision(BaseModel):
    """Durable policy decision that selected one staged run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    based_on_run_id: str = Field(min_length=1)
    decision: Mapping[str, JsonValue] = Field(default_factory=dict)
    checkpoint: Mapping[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_payloads(self) -> RunStageDecision:
        object.__setattr__(self, "decision", freeze_json_mapping(self.decision))
        object.__setattr__(self, "checkpoint", freeze_json_mapping(self.checkpoint))
        return self


class RunStageLineage(BaseModel):
    """Durable identity of one run within a notebook-driven sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_id: str = Field(min_length=1)
    index: int = Field(ge=0)
    previous_run_id: str | None = Field(default=None, min_length=1)
    decision: RunStageDecision | None = None

    @model_validator(mode="after")
    def validate_predecessor(self) -> RunStageLineage:
        if self.index == 0 and self.previous_run_id is not None:
            raise ValueError("the first run stage cannot have a predecessor")
        if self.index > 0 and self.previous_run_id is None:
            raise ValueError("a later run stage requires a predecessor")
        if (
            self.decision is not None
            and self.decision.based_on_run_id != self.previous_run_id
        ):
            raise ValueError("stage decision must be based on its predecessor run")
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
    stage: RunStageLineage | None = None
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
