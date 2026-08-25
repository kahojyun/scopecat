"""Repository boundary for durable analysis publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.analysis import AnalysisSubject, ProjectAnalysisSubject
from scopecat.records.content import BytesWrite, ContentEntry, ModelWrite

_PROJECT_SUBJECT = ProjectAnalysisSubject()


class AnalysisPublicationSummary(BaseModel):
    """Bounded index projection for one analysis publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: AnalysisSubject
    record: ContentEntry
    title: str = Field(min_length=1)
    analysis_key: str = Field(min_length=1)
    revision: int = Field(ge=1)
    publication_hash: str = Field(min_length=1)
    published_at: datetime
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
    """Prepared analysis index, content, and payload refs published atomically."""

    subject: AnalysisSubject
    record: ContentEntry
    entries: tuple[ContentEntry, ...]
    analysis_key: str
    revision: int
    publication_hash: str
    title: str
    step_id: str | None
    input_count: int
    output_count: int
    models: tuple[ModelWrite, ...] = ()
    bytes: tuple[BytesWrite, ...] = ()


class AnalysisRepository(Protocol):
    """Durable project-level analysis publication storage."""

    def list_summaries(
        self,
        *,
        subject: AnalysisSubject = _PROJECT_SUBJECT,
        limit: int,
        before: int | None,
    ) -> AnalysisPublicationPage: ...

    def read_publication(
        self,
        record_id: str,
        *,
        subject: AnalysisSubject = _PROJECT_SUBJECT,
    ) -> AnalysisPublicationSummary: ...

    def latest_publication(
        self,
        analysis_key: str,
        *,
        subject: AnalysisSubject = _PROJECT_SUBJECT,
    ) -> AnalysisPublicationSummary | None: ...

    def list_contents(
        self,
        record_id: str,
        *,
        limit: int,
        before: int | None = None,
    ) -> AnalysisContentPage: ...

    def read_content(self, record_id: str, content_id: str) -> ContentEntry: ...

    def publish(self, publication: AnalysisPublication) -> None: ...

    def read_model[TModel: BaseModel](
        self,
        record_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> TModel: ...

    def read_bytes(self, record_id: str, ref: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class AnalysisContentPage:
    """Newest-first bounded page of project-analysis-owned content."""

    items: tuple[ContentEntry, ...] = ()
    next_cursor: int | None = None


__all__ = [
    "AnalysisContentPage",
    "AnalysisPublication",
    "AnalysisPublicationPage",
    "AnalysisPublicationSummary",
    "AnalysisRepository",
]
