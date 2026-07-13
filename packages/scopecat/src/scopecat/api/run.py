"""Run facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from scopecat.api._services import workspace_services
from scopecat.api.analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.api.data import Data
from scopecat.application.services import WorkspaceServices
from scopecat.records.artifact import RunArtifactEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunManifest
from scopecat.records.run_plan import RunPlanRecord
from scopecat.records.run_request import RunRequest
from scopecat.run_comparison import RunComparisonView
from scopecat.run_comparison.service import list_run_comparisons
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
    load_run_plan,
    load_run_request,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)

if TYPE_CHECKING:
    from scopecat.run_overview import RunOverview
    from scopecat.runs.execution import RunExecutionInspection


class RunSession(Protocol):
    @property
    def reviewer(self) -> str: ...

    @property
    def operator(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def _services(self) -> WorkspaceServices: ...

    def overview(self, run: RunHandle | RunSelector) -> RunOverview: ...


@dataclass(frozen=True)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    manifest: RunManifest

    @property
    def id(self) -> str:
        return self.manifest.run_id

    @property
    def config(self) -> ConfigProfileSnapshot:
        return load_run_config(
            run_id=self.id,
            services=workspace_services(self.session),
        )

    @property
    def request(self) -> RunRequest | None:
        """Load the independently persisted operator request, when present."""

        return load_run_request(
            run_id=self.id,
            services=workspace_services(self.session),
        )

    @property
    def plan(self) -> RunPlanRecord:
        """Load the independently persisted accepted-plan evidence."""

        return load_run_plan(
            run_id=self.id,
            services=workspace_services(self.session),
        )

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(
            artifact.id
            for artifact in list_run_artifacts(
                run_id=self.id,
                services=workspace_services(self.session),
            )
        )

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(
            dataset.id
            for dataset in load_run(
                run_id=self.id,
                services=workspace_services(self.session),
            ).manifest.datasets
        )

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=self.id,
            services=workspace_services(self.session),
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
        metadata: dict[str, object] | None = None,
    ) -> RunArtifactEntry:
        return attach_run_artifact(
            services=workspace_services(self.session),
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
            services=workspace_services(self.session),
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
            services=workspace_services(self.session),
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
            services=workspace_services(self.session),
            selector=selector,
            expected_kind=expected_kind,
        )

    def overview(self) -> RunOverview:
        return self.session.overview(self)

    def inspect_execution(self) -> RunExecutionInspection:
        """Read durable execution evidence without mutating or recovering the run."""

        from scopecat.runs.execution import inspect_run_execution

        return inspect_run_execution(
            run_id=self.id,
            services=workspace_services(self.session),
        )

    def comparisons(self) -> tuple[RunComparisonView, ...]:
        return tuple(
            list_run_comparisons(
                run_id=self.id,
                services=workspace_services(self.session),
            )
        )


def run_handle_id(run: RunHandle | RunSelector) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return selected_run_id(run)


__all__ = ["RunHandle", "RunSession", "run_handle_id"]
