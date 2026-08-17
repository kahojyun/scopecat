"""Repository boundary for project-level analysis publications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.artifact import RunContentEntry
from scopecat.runs.repository import RunBytesWrite, RunModelWrite


class AnalysisPublicationManifest(BaseModel):
    """Atomic project-level publication index and its owned content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: RunContentEntry
    contents: tuple[RunContentEntry, ...] = ()

    @model_validator(mode="after")
    def validate_contents(self) -> AnalysisPublicationManifest:
        if self.record.role != "record" or self.record.kind != "analysis":
            raise ValueError("analysis publication record identity is invalid")
        ids = tuple(entry.id for entry in self.contents)
        if self.record.id not in ids:
            raise ValueError("analysis publication contents must include its record")
        if len(ids) != len(set(ids)):
            raise ValueError("analysis publication content ids must be unique")
        return self


class AnalysisPublicationSummary(BaseModel):
    """Bounded index projection for one project-level publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: RunContentEntry
    title: str = Field(min_length=1)
    analysis_key: str = Field(min_length=1)
    revision: int = Field(ge=1)
    publication_hash: str = Field(min_length=1)
    step_id: str | None = None
    input_count: int = Field(ge=0)
    output_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_record(self) -> AnalysisPublicationSummary:
        if self.record.role != "record" or self.record.kind != "analysis":
            raise ValueError("analysis publication summary identity is invalid")
        return self


class AnalysisPublicationPage(BaseModel):
    """Newest-first keyset page from the project analysis index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[AnalysisPublicationSummary, ...] = ()
    next_cursor: int | None = Field(default=None, ge=1)


@dataclass(frozen=True, slots=True)
class AnalysisPublication:
    """Prepared project-level analysis content published atomically."""

    manifest: AnalysisPublicationManifest
    analysis_key: str
    revision: int
    publication_hash: str
    title: str
    step_id: str | None
    input_count: int
    output_count: int
    models: tuple[RunModelWrite, ...] = ()
    bytes: tuple[RunBytesWrite, ...] = ()


class AnalysisRepository(Protocol):
    """Durable project-level analysis publication storage."""

    def list_summaries(
        self,
        *,
        limit: int,
        before: int | None,
    ) -> AnalysisPublicationPage: ...

    def read_manifest(self, record_id: str) -> AnalysisPublicationManifest: ...

    def latest_manifest(
        self,
        analysis_key: str,
    ) -> AnalysisPublicationManifest | None: ...

    def publish(self, publication: AnalysisPublication) -> None: ...

    def read_model[TModel: BaseModel](
        self,
        record_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> TModel: ...

    def read_bytes(self, record_id: str, ref: str) -> bytes: ...


__all__ = [
    "AnalysisPublication",
    "AnalysisPublicationManifest",
    "AnalysisPublicationPage",
    "AnalysisPublicationSummary",
    "AnalysisRepository",
]
