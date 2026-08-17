"""Repository boundary for durable run state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.content import BytesWrite, ContentEntry, ModelWrite
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.run import RunSnapshot

if TYPE_CHECKING:
    from scopecat.analysis.repository import (
        AnalysisPublication,
        AnalysisPublicationPage,
        AnalysisPublicationSummary,
    )

type RunContentRole = Literal["artifact", "dataset", "record"]


@dataclass(frozen=True, slots=True)
class RunContentPage:
    """Newest-first bounded page from one run's relational content index."""

    items: tuple[ContentEntry, ...] = ()
    next_cursor: int | None = None


@dataclass(frozen=True, slots=True)
class TerminalRunCommit:
    """Terminal outcome and evidence to apply to the durable run."""

    run_id: str
    outcome: RunOutcome
    contents: tuple[ContentEntry, ...] = ()
    models: tuple[ModelWrite, ...] = ()


@dataclass(frozen=True, slots=True)
class RunContentPublication:
    """Content refs and catalog entries made visible as one operation."""

    run_id: str
    entries: tuple[ContentEntry, ...]
    models: tuple[ModelWrite, ...] = ()
    bytes: tuple[BytesWrite, ...] = ()


class RunRepository(Protocol):
    """Durable run repository shared by use cases and storage adapters."""

    def exists(self, run_id: str, ref: str) -> bool: ...

    def read_snapshot(self, run_id: str) -> RunSnapshot: ...

    def list_contents(
        self,
        run_id: str,
        *,
        limit: int,
        before: int | None = None,
        role: RunContentRole | None = None,
        kind: str | None = None,
    ) -> RunContentPage: ...

    def read_content(
        self,
        run_id: str,
        *,
        role: RunContentRole,
        content_id: str,
    ) -> ContentEntry: ...

    def commit_terminal(self, commit: TerminalRunCommit) -> RunSnapshot: ...

    def publish_content(
        self,
        publication: RunContentPublication,
    ) -> None: ...

    def publish_analysis(self, publication: AnalysisPublication) -> None: ...

    def list_analysis_publications(
        self,
        run_id: str,
        *,
        limit: int,
        before: int | None = None,
    ) -> AnalysisPublicationPage: ...

    def read_analysis_publication(
        self,
        run_id: str,
        record_id: str,
    ) -> AnalysisPublicationSummary: ...

    def latest_analysis_publication(
        self,
        run_id: str,
        analysis_key: str,
    ) -> AnalysisPublicationSummary | None: ...

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot: ...

    def read_model[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> TModel: ...

    def read_measurement_records(
        self,
        run_id: str,
        ref: str,
    ) -> list[MeasurementRecord]: ...

    def read_text(self, run_id: str, ref: str) -> str: ...

    def read_bytes(self, run_id: str, ref: str) -> bytes: ...
