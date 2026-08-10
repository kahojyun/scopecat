"""Remote run operations backed by the daemon HTTP transport."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from scopecat.analysis.service import (
    AnalysisDataOutput,
    AnalysisFigureOutput,
    AnalysisInput,
    AnalysisOutput,
    AnalysisParameterProposalOutput,
    AnalysisTableOutput,
    SavedAnalysis,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import MeasurementPage, RunAnalysisListView, RunAnalysisView
from scopecat.daemon.wire import (
    AnalysisDataOutputPayload,
    AnalysisFigureOutputPayload,
    AnalysisInputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisTableOutputPayload,
    RunAttachmentCommand,
)
from scopecat.records._metadata import validate_json_metadata
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)


@dataclass(frozen=True, slots=True)
class RemoteRunOperations:
    """Run handle storage operations owned by one daemon transport."""

    client: DaemonClient

    def load_manifest(self, run_id: str) -> RunManifest:
        return self.client.get_run(run_id).manifest

    def load_config(self, run_id: str) -> ConfigProfileSnapshot:
        return self.client.run_config(run_id).config

    def load_request(self, run_id: str) -> RunRequest:
        return self.client.run_request(run_id).request

    def load_measurement_dataset(
        self,
        run_id: str,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.client.dataset_content(run_id, selector)

    def load_measurement_page(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage:
        return self.client.measurements(run_id, limit=limit, offset=offset)

    def save_analysis(
        self,
        *,
        run_id: str,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        payloads = tuple(_analysis_output_payload(output) for output in outputs)
        output_proposals = tuple(
            payload.content
            for payload in payloads
            if isinstance(payload, AnalysisParameterProposalOutputPayload)
        )
        if output_proposals != tuple(parameter_proposals):
            raise ValueError("analysis parameter proposals must match proposal outputs")
        receipt = self.client.save_analysis(
            run_id,
            AnalysisSaveCommand(
                title=title,
                analysis_key=analysis_key,
                step_id=step_id,
                inputs=tuple(_analysis_input_payload(item) for item in inputs),
                outputs=payloads,
            ),
        )
        return SavedAnalysis(
            record=receipt.record,
            analysis_key=receipt.analysis_key,
            inputs=tuple(inputs),
        )

    def analyses(self, run_id: str) -> RunAnalysisListView:
        return self.client.analyses(run_id)

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        return self.client.analysis(run_id, selector)

    def attach(
        self,
        *,
        run_id: str,
        path: str | Path | None,
        key: str,
        kind: str,
        text: str | None,
        content: bytes | None,
        filename: str | None,
        media_type: str | None,
        metadata: Mapping[str, JsonValue] | None,
    ) -> RunContentEntry:
        source_path = None if path is None else Path(path)
        if source_path is not None:
            if text is not None or content is not None:
                raise ValueError("run attachment requires exactly one content source")
            content = source_path.read_bytes()
            filename = filename or source_path.name
        encoded = None if content is None else b64encode(content).decode("ascii")
        return self.client.attach(
            run_id,
            RunAttachmentCommand(
                key=key,
                kind=kind,
                text=text,
                content_base64=encoded,
                filename=filename,
                media_type=media_type,
                metadata=dict(metadata or {}),
            ),
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesResult:
        view = self.client.artifact_bytes(
            run_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunArtifactBytesResult(
            artifact=view.artifact,
            content=view.content_bytes(),
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        return self.client.artifact_text(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        return self.client.artifact_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        return self.client.record_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )


def _analysis_input_payload(value: AnalysisInput) -> AnalysisInputPayload:
    return AnalysisInputPayload(
        target=value.target,
        kind=value.kind,
        role=value.role,
        title=value.title,
        metadata=(
            None if value.metadata is None else validate_json_metadata(value.metadata)
        ),
    )


def _analysis_output_payload(value: AnalysisOutput) -> AnalysisOutputPayload:
    metadata = validate_json_metadata(value.metadata)
    if isinstance(value, AnalysisDataOutput):
        return AnalysisDataOutputPayload(
            kind="data",
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    if isinstance(value, AnalysisTableOutput):
        return AnalysisTableOutputPayload(
            kind="table",
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    if isinstance(value, AnalysisFigureOutput):
        return AnalysisFigureOutputPayload(
            kind="figure",
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    assert isinstance(value, AnalysisParameterProposalOutput)
    return AnalysisParameterProposalOutputPayload(
        kind="parameter_change_proposal",
        title=value.title,
        content=value.content,
        metadata=metadata,
    )


__all__ = ["RemoteRunOperations"]
