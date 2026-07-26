"""Accepted run snapshots and terminal outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import Problem
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigContentHash

RunResult = Literal["succeeded", "failed", "cancelled"]
RunCertainty = Literal["known", "indeterminate"]
RunStatus = Literal[
    "planned",
    "completed",
    "failed",
    "interrupted",
    "unknown",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


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
    analysis_record_ids: tuple[str, ...] = Field(min_length=1)
    proposal_ids: tuple[str, ...] = Field(min_length=1)
    base_config_content_hash: ConfigContentHash
    content_hash: ConfigContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> AnalysisCandidateRunConfigSource:
        if (
            not self.source_run_id
            or any(not record_id for record_id in self.analysis_record_ids)
            or any(not proposal_id for proposal_id in self.proposal_ids)
        ):
            raise ValueError("analysis candidate run source identity must be non-empty")
        if len(self.analysis_record_ids) != len(set(self.analysis_record_ids)):
            raise ValueError("analysis candidate run source analyses must be unique")
        if len(self.proposal_ids) != len(set(self.proposal_ids)):
            raise ValueError("analysis candidate run source proposals must be unique")
        return self


type RunConfigSource = Annotated[
    ConfigRegistryRunConfigSource | AnalysisCandidateRunConfigSource,
    Field(discriminator="kind"),
]


class RunOutcome(BaseModel):
    """Immutable durable outcome established when one run becomes terminal."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    run_id: str
    result: RunResult
    certainty: RunCertainty
    finished_at: datetime = Field(default_factory=utc_now)
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> RunOutcome:
        has_problems = bool(self.problems)
        if self.result == "succeeded":
            if self.certainty != "known":
                msg = "a succeeded run outcome must be known"
                raise ValueError(msg)
            if has_problems:
                msg = "a succeeded run outcome cannot contain problems"
                raise ValueError(msg)
            return self
        if not has_problems:
            msg = "a non-succeeded run outcome requires a problem"
            raise ValueError(msg)
        return self

    @property
    def status(self) -> RunStatus:
        """Return the presentation status derived from durable outcome facts."""

        if self.result == "succeeded":
            return "completed"
        if self.result == "cancelled":
            return "interrupted"
        if self.certainty == "indeterminate":
            return "unknown"
        return "failed"


class RunManifest(BaseModel):
    """Accepted snapshot plus content and an optional terminal outcome."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    outcome: RunOutcome | None = None
    config_content_hash: ConfigContentHash
    config_source: RunConfigSource | None = None
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
