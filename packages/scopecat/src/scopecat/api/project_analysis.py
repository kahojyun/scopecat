"""Remote operations for project-level multi-run analysis publications."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.analysis.datasets import DerivedDataset, DerivedDatasetSchema
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
)
from scopecat.api._remote import analysis_input_payload, analysis_output_payload
from scopecat.api.published_analysis import PublishedAnalysis, PublishedAnalysisPage
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import (
    ProjectAnalysisPage,
    ProjectAnalysisView,
)
from scopecat.daemon.wire import AnalysisSaveCommand
from scopecat.kernel.json_types import JsonValue
from scopecat.records.analysis import AnalysisExecution
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunRecordJsonResult,
)


@dataclass(frozen=True, slots=True)
class RemoteProjectAnalysisOperations:
    """Publication owner and typed content source for one daemon project."""

    client: DaemonClient

    def save_analysis(
        self,
        *,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        executions: Sequence[AnalysisExecution],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        if parameter_proposals:
            raise TypeError("project analysis cannot publish parameter proposals yet")
        receipt = self.client.save_project_analysis(
            AnalysisSaveCommand(
                title=title,
                analysis_key=analysis_key,
                step_id=step_id,
                inputs=tuple(analysis_input_payload(item) for item in inputs),
                executions=tuple(executions),
                outputs=tuple(analysis_output_payload(item) for item in outputs),
            )
        )
        return SavedAnalysis(
            record=receipt.record,
            analysis_key=receipt.analysis_key,
            inputs=tuple(inputs),
            executions=tuple(executions),
            outputs=tuple(outputs),
        )

    def published_analyses(
        self,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> PublishedAnalysisPage:
        summaries = self.summaries(limit=limit, before=before)
        return PublishedAnalysisPage(
            items=tuple(
                self.published_analysis(summary.entry.id) for summary in summaries.items
            ),
            next_cursor=summaries.next_cursor,
        )

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        return PublishedAnalysis(
            source=self, view=self.client.project_analysis(selector)
        )

    def summaries(
        self,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> ProjectAnalysisPage:
        return self.client.project_analyses(limit=limit, before=before)

    def view(self, selector: str) -> ProjectAnalysisView:
        return self.client.project_analysis(selector)

    def _load_analysis_dataset(
        self,
        analysis_id: str,
        selector: str,
    ) -> DerivedDataset:
        content = self.client.project_analysis_content_bytes(analysis_id, selector)
        if content.entry.data_schema is None:
            raise ValueError("analysis dataset is missing its semantic schema")
        return DerivedDataset.from_arrow_ipc(
            content.content_bytes(),
            schema=DerivedDatasetSchema.model_validate(content.entry.data_schema),
        )

    def _analysis_artifact_entry(
        self,
        analysis_id: str,
        selector: str,
    ) -> RunContentEntry:
        view = self.view(analysis_id)
        try:
            return next(entry for entry in view.contents if entry.id == selector)
        except StopIteration:
            raise KeyError(f"analysis has no artifact: {selector}") from None

    def _analysis_artifact_bytes(
        self,
        analysis_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        content = self.client.project_analysis_content_bytes(analysis_id, selector)
        _require_kind(content.entry.kind, expected_kind)
        return RunArtifactBytesResult(
            artifact=content.entry,
            content=content.content_bytes(),
        )

    def _analysis_artifact_text(
        self,
        analysis_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        result = self._analysis_artifact_bytes(
            analysis_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunArtifactTextResult(
            artifact=result.artifact,
            content=result.content.decode(),
        )

    def _analysis_artifact_json(
        self,
        analysis_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        result = self._analysis_artifact_text(
            analysis_id,
            selector,
            expected_kind=expected_kind,
        )
        value = cast("object", json.loads(result.content))
        if not isinstance(value, dict):
            raise TypeError("analysis JSON artifact must contain an object")
        return RunArtifactJsonResult(
            artifact=result.artifact,
            content=cast("dict[str, JsonValue]", value),
        )

    def _analysis_record_json(
        self,
        analysis_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        del analysis_id, selector, expected_kind
        raise TypeError("project analysis does not own parameter proposal records")


def _require_kind(actual: str, expected: str | None) -> None:
    if expected is not None and actual != expected:
        raise TypeError(f"analysis content is {actual!r}, not {expected!r}")


__all__ = ["RemoteProjectAnalysisOperations"]
