"""Run facade handles for notebook workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from pydantic import JsonValue

from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
    save_analysis,
)
from scopecat.api.analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.api.data import Data
from scopecat.application.services import WorkspaceServices
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.selectors import RunSelector, selected_run_id
from scopecat.runs.service import (
    list_run_artifacts,
    load_run,
    load_run_config,
    load_run_request,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)


class RunSession(Protocol):
    @property
    def reviewer(self) -> str: ...

    @property
    def operator(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def services(self) -> WorkspaceServices: ...


@dataclass(frozen=True)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    id: str

    @property
    def manifest(self) -> RunManifest:
        """Load the current durable manifest for this run."""

        return load_run(run_id=self.id, services=self.session.services)

    @property
    def config(self) -> ConfigProfileSnapshot:
        return load_run_config(
            run_id=self.id,
            services=self.session.services,
        )

    @property
    def request(self) -> RunRequest | None:
        """Load the independently persisted operator request, when present."""

        return load_run_request(
            run_id=self.id,
            services=self.session.services,
        )

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(
            artifact.id
            for artifact in list_run_artifacts(
                run_id=self.id,
                services=self.session.services,
            )
        )

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(
            dataset.id
            for dataset in load_run(
                run_id=self.id,
                services=self.session.services,
            ).datasets
        )

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=self.id,
            services=self.session.services,
            selector=selector,
        )

    def data(self) -> Data:
        return Data(run=self)

    def analysis(
        self,
        title: str,
        *,
        key: str | None = None,
        step_id: str | None = None,
    ) -> Analysis:
        return Analysis(run=self, title=title, key=key, step_id=step_id)

    def save_analysis(
        self,
        *,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        """Persist analysis through this run's owning execution boundary."""

        return save_analysis(
            services=self.session.services,
            run_id=self.id,
            title=title,
            analysis_key=analysis_key,
            step_id=step_id,
            inputs=inputs,
            outputs=outputs,
            parameter_proposals=parameter_proposals,
        )

    def analyze(self, step: AnalysisStep, *, key: str | None = None) -> Analysis:
        analysis = step.run(
            AnalysisContext(
                run=self,
                data=self.data(),
                default_key=key or step.id,
                step_id=step.id,
            )
        )
        if analysis.key is None or analysis.step_id is None:
            analysis = replace(
                analysis,
                key=analysis.key or key or step.id,
                step_id=analysis.step_id or step.id,
            )
        return analysis

    def attach(
        self,
        path: str | Path | None = None,
        *,
        key: str,
        kind: str = "attachment",
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> RunContentEntry:
        return attach_run_artifact(
            services=self.session.services,
            run_id=self.id,
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
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=self.id,
            services=self.session.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=self.id,
            services=self.session.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        return read_run_record_json(
            run_id=self.id,
            services=self.session.services,
            selector=selector,
            expected_kind=expected_kind,
        )


def run_handle_id(run: RunHandle | RunSelector) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return selected_run_id(run)
