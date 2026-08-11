"""Typed read facade for one durable analysis publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.analysis.datasets import DerivedDataset
from scopecat.daemon.views import RunAnalysisView
from scopecat.records.analysis import (
    AnalysisArtifactRecordOutput,
    AnalysisDatasetRecordOutput,
    AnalysisExecution,
    AnalysisFact,
    AnalysisFactRecordOutput,
    AnalysisFigureRecordOutput,
    AnalysisFigureView,
    AnalysisParameterProposalRecordOutput,
    AnalysisParameterProposalReference,
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisTableRecordOutput,
    AnalysisTableView,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import require_artifact
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
)


class _PublishedAnalysisRun(Protocol):
    @property
    def manifest(self) -> RunManifest: ...

    def derived_dataset(self, selector: str) -> DerivedDataset: ...

    def artifact_text(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult: ...

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult: ...

    def artifact_bytes(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult: ...


@dataclass(frozen=True, slots=True)
class PublishedAnalysisArtifact:
    """One analysis-owned artifact with typed payload access."""

    run: _PublishedAnalysisRun
    output: AnalysisArtifactRecordOutput

    @property
    def entry(self) -> RunContentEntry:
        return require_artifact(
            manifest=self.run.manifest,
            selector=self.output.content.artifact_id,
            expected_kind="analysis_artifact",
        )

    def bytes(self) -> bytes:
        return self.run.artifact_bytes(
            self.output.content.artifact_id,
            expected_kind="analysis_artifact",
        ).content

    def text(self) -> str:
        return self.run.artifact_text(
            self.output.content.artifact_id,
            expected_kind="analysis_artifact",
        ).content

    def json(self) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self.run.artifact_json(
                self.output.content.artifact_id,
                expected_kind="analysis_artifact",
            ).content,
        )


@dataclass(frozen=True, slots=True)
class PublishedAnalysis:
    """One immutable analysis record with output-ID based typed access."""

    run: _PublishedAnalysisRun
    view: RunAnalysisView

    @property
    def id(self) -> str:
        return self.view.entry.id

    @property
    def key(self) -> str | None:
        return self.view.analysis.key

    @property
    def title(self) -> str:
        return self.view.analysis.title

    @property
    def revision(self) -> int:
        return self.view.analysis.revision

    @property
    def publication_hash(self) -> str:
        return self.view.analysis.publication_hash

    @property
    def outputs(self) -> tuple[AnalysisRecordOutput, ...]:
        return tuple(self.view.analysis.outputs)

    @property
    def inputs(self) -> tuple[AnalysisRecordInput, ...]:
        return tuple(self.view.analysis.inputs)

    @property
    def executions(self) -> tuple[AnalysisExecution, ...]:
        return tuple(self.view.analysis.executions)

    def output(self, id: str) -> AnalysisRecordOutput:
        try:
            return next(output for output in self.outputs if output.id == id)
        except StopIteration:
            raise KeyError(f"analysis has no output: {id}") from None

    def fact(self, id: str) -> AnalysisFact:
        return self._output(id, AnalysisFactRecordOutput).content

    def dataset(self, id: str) -> DerivedDataset:
        output = self._output(id, AnalysisDatasetRecordOutput)
        return self.run.derived_dataset(output.content.dataset_id)

    def artifact(self, id: str) -> PublishedAnalysisArtifact:
        return PublishedAnalysisArtifact(
            run=self.run,
            output=self._output(id, AnalysisArtifactRecordOutput),
        )

    def table(self, id: str) -> AnalysisTableView:
        return self._output(id, AnalysisTableRecordOutput).content

    def figure(self, id: str) -> AnalysisFigureView:
        return self._output(id, AnalysisFigureRecordOutput).content

    def proposal(self, id: str) -> AnalysisParameterProposalReference:
        return self._output(id, AnalysisParameterProposalRecordOutput).content

    def _output[OutputT: AnalysisRecordOutput](
        self,
        id: str,
        output_type: type[OutputT],
    ) -> OutputT:
        output = self.output(id)
        if not isinstance(output, output_type):
            raise TypeError(
                f"analysis output {id!r} is {output.kind}, not {output_type.__name__}"
            )
        return output


__all__ = ["PublishedAnalysis", "PublishedAnalysisArtifact"]
