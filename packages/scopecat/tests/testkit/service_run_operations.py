"""In-process run operations for repository tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
    save_analysis,
)
from scopecat.application.services import ProjectStateServices
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.service import (
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)


@dataclass(frozen=True, slots=True)
class ServiceRunOperations:
    services: ProjectStateServices

    def load_manifest(self, run_id: str) -> RunManifest:
        return self.services.runs.read_manifest(run_id)

    def load_config(self, run_id: str) -> ConfigProfileSnapshot:
        return self.services.runs.read_config_profile_snapshot(run_id)

    def load_request(self, run_id: str) -> RunRequest:
        return load_run_request(run_id=run_id, services=self.services)

    def measurements(
        self,
        run_id: str,
        *,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=run_id,
            services=self.services,
            selector=selector,
        )

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
        return save_analysis(
            services=self.services,
            run_id=run_id,
            title=title,
            analysis_key=analysis_key,
            step_id=step_id,
            inputs=inputs,
            outputs=outputs,
            parameter_proposals=parameter_proposals,
        )

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
        return attach_run_artifact(
            services=self.services,
            run_id=run_id,
            path=path,
            key=key,
            kind=kind,
            text=text,
            content=content,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesResult:
        return read_run_artifact_bytes(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        return read_run_record_json(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )
