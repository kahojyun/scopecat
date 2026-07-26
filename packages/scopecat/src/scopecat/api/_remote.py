"""Remote run operations backed by the daemon HTTP transport."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue, RootModel, TypeAdapter

from scopecat.analysis.service import (
    AnalysisArtifactSpec,
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import RunAnalysisListView, RunAnalysisView
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisInputPayload,
    AnalysisJsonOutputPayload,
    AnalysisNoteOutputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    RunAttachmentCommand,
)
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

_JSON_MAPPING = TypeAdapter(dict[str, JsonValue])


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

    def measurements(
        self,
        run_id: str,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.client.dataset_content(run_id, selector)

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
            output_artifacts=receipt.output_artifacts,
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


class _JsonValue(RootModel[JsonValue]):
    pass


def _analysis_input_payload(value: AnalysisInput) -> AnalysisInputPayload:
    return AnalysisInputPayload(
        target=value.target,
        kind=value.kind,
        role=value.role,
        title=value.title,
        metadata=(
            None
            if value.metadata is None
            else _JSON_MAPPING.validate_python(value.metadata)
        ),
    )


def _analysis_output_payload(value: AnalysisOutput) -> AnalysisOutputPayload:
    metadata = _JSON_MAPPING.validate_python(value.metadata)
    if value.kind == "note":
        if not isinstance(value.content, str):
            raise ValueError("remote analysis note content must be text")
        return AnalysisNoteOutputPayload(
            kind=value.kind,
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    if value.kind in {"table", "array", "figure"}:
        return AnalysisJsonOutputPayload(
            kind=cast("Literal['table', 'array', 'figure']", value.kind),
            title=value.title,
            content=_JsonValue.model_validate(value.content).root,
            metadata=metadata,
        )
    if value.kind == "artifact":
        if not isinstance(value.content, AnalysisArtifactSpec):
            raise ValueError("remote analysis artifact output has invalid content")
        return AnalysisArtifactOutputPayload(
            kind=value.kind,
            title=value.title,
            artifact_kind=value.content.kind,
            content_base64=b64encode(value.content.content).decode("ascii"),
            artifact_id=value.content.artifact_id,
            filename=value.content.filename,
            media_type=value.content.media_type,
            artifact_metadata=_JSON_MAPPING.validate_python(value.content.metadata),
            metadata=metadata,
        )
    if value.kind == "parameter_change_proposal":
        if not isinstance(value.content, ParameterChangeProposal):
            raise ValueError("remote analysis proposal output has invalid content")
        return AnalysisParameterProposalOutputPayload(
            kind=value.kind,
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    raise ValueError(
        "remote analysis supports note, table, array, figure, artifact, "
        "and parameter change proposal outputs"
    )


__all__ = ["RemoteRunOperations"]
