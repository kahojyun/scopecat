"""Typed read facade for one durable analysis publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from scopecat.analysis.datasets import DerivedDataset
from scopecat.analysis.facts import AnalysisFactSchema
from scopecat.config.candidates import (
    CandidateConfig,
    CandidateSelection,
    candidate_config_from_proposals,
)
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
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisTableRecordOutput,
    AnalysisTableView,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.runs.access import require_artifact
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunRecordJsonResult,
)
from scopecat.sdk.compute import PYTHON_JSON_CODEC


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

    def record_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult: ...


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
    def step_id(self) -> str | None:
        return self.view.analysis.step_id

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

    @property
    def parameter_proposals(self) -> tuple[ParameterChangeProposal, ...]:
        return tuple(
            self.proposal(output.id)
            for output in self.outputs
            if isinstance(output, AnalysisParameterProposalRecordOutput)
        )

    def candidate_config(
        self,
        selection: CandidateSelection = None,
    ) -> CandidateConfig:
        return candidate_config_from_proposals(
            self.parameter_proposals,
            selection=selection,
        )

    def output(self, id: str) -> AnalysisRecordOutput:
        try:
            return next(output for output in self.outputs if output.id == id)
        except StopIteration:
            raise KeyError(f"analysis has no output: {id}") from None

    def fact(self, id: str) -> AnalysisFact:
        return self._output(id, AnalysisFactRecordOutput).content

    def fact_as[ValueT](
        self,
        id: str,
        schema: AnalysisFactSchema[ValueT],
    ) -> ValueT:
        """Validate and reconstruct one structured fact with a local type."""

        fact = self.fact(id)
        if fact.schema_id != schema.id:
            raise TypeError(
                f"analysis fact {id!r} uses schema {fact.schema_id!r}, "
                f"not {schema.id!r}"
            )
        if fact.schema_hash != schema.schema_hash:
            raise TypeError(
                f"analysis fact {id!r} schema fingerprint does not match {schema.id!r}"
            )
        if fact.codec != PYTHON_JSON_CODEC:
            raise TypeError(
                f"analysis fact {id!r} uses unsupported codec {fact.codec!r}"
            )
        return schema.decode(fact.value)

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

    def proposal(self, id: str) -> ParameterChangeProposal:
        output = self._output(id, AnalysisParameterProposalRecordOutput)
        return ParameterChangeProposal.model_validate(
            self.run.record_json(
                output.content.proposal_id,
                expected_kind="parameter_change_proposal",
            ).content
        )

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
