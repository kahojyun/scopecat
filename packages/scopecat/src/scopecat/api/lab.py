"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Literal, Self

from scopecat.api._config import LabConfigOperations
from scopecat.api._control import LabControlOperations
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.analysis import AnalysisContext, AnalysisStep
from scopecat.api.instruments import LabInstrumentOperations
from scopecat.api.project_analysis import RemoteProjectAnalysisOperations
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.api.review import ExperimentReviewHandle
from scopecat.api.run import RunHandle, RunHandlePage, run_handle_id
from scopecat.authoring.experiments import Experiment, ExperimentInvocation
from scopecat.config.candidates import CandidateConfig
from scopecat.control.models import ControlRunState
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth, ProjectAnalysisPage
from scopecat.inspection import CompiledProgramInspectionQuery
from scopecat.planning.preview import PreviewCoordinateMode
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.program.values import MetadataValue
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource
from scopecat.runs.selectors import RunSelector

type ExperimentSpec = ExperimentInvocation | Experiment[...]
type PreviewPoint = int | Literal["first", "middle", "last"]


@dataclass(frozen=True, slots=True)
class PreparedLabExperiment:
    """A config-bound invocation ready for local planning and daemon execution."""

    lab: LabClient
    invocation: ExperimentInvocation
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None

    def preview(
        self,
        *,
        point: PreviewPoint = "first",
        coordinates: Mapping[str, object] | None = None,
        coordinate_mode: PreviewCoordinateMode = "exact",
        inspection_query: CompiledProgramInspectionQuery | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self.lab.preview_invocation(
            self.invocation,
            config=self.config,
            point=point,
            coordinates=coordinates,
            coordinate_mode=coordinate_mode,
            inspection_query=inspection_query,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        return self.lab.execute_invocation(
            self.invocation,
            config=self.config,
            config_source=self.config_source,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def review(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentReviewHandle:
        return self.lab.review_invocation(
            self.invocation,
            config=self.config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )


class LabClient:
    """Notebook operations backed by one daemon HTTP owner."""

    def __init__(
        self,
        daemon: str | DaemonClient,
        *,
        build_experiment_system: ExperimentSystemBuilder | None = None,
        config: ConfigProfileSnapshot | None = None,
        operator: str = "operator",
    ) -> None:
        self._owns_client = isinstance(daemon, str)
        self._client = DaemonClient(daemon) if isinstance(daemon, str) else daemon
        self._runs = RemoteRunOperations(self._client)
        self._analyses = RemoteProjectAnalysisOperations(self._client)
        self._config = LabConfigOperations(
            client=self._client,
            runs=self._runs,
            default_config=config,
            operator=operator,
        )
        self._control = LabControlOperations(self._client)
        self._instruments = LabInstrumentOperations(
            self._client,
            operator=operator,
        )
        self._runner = _DaemonRunner(self._client, build_experiment_system)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def run_operations(self) -> RemoteRunOperations:
        return self._runs

    @property
    def config(self) -> LabConfigOperations:
        return self._config

    @property
    def control(self) -> LabControlOperations:
        return self._control

    @property
    def instruments(self) -> LabInstrumentOperations:
        return self._instruments

    def health(self) -> DaemonHealth:
        return self._control.health()

    def runs(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        state: ControlRunState | None = None,
    ) -> RunHandlePage:
        """Load one bounded newest-first page of run handles."""

        page = self._control.runs(limit=limit, before=before, state=state)
        return RunHandlePage(
            items=tuple(RunHandle(session=self, id=item.run_id) for item in page.items),
            next_cursor=page.next_cursor,
        )

    def analysis(
        self,
        title: str,
        *,
        key: str | None = None,
    ) -> AnalysisContext:
        """Start a project publication over explicit completed-run inputs."""

        return AnalysisContext(
            owner=self._analyses,
            default_title=title,
            default_key=key,
        )

    def analyze(
        self,
        step: AnalysisStep,
        *,
        key: str | None = None,
    ) -> PublishedAnalysis:
        """Run and durably publish one project-level analysis step."""

        analysis = step.run(
            AnalysisContext(
                owner=self._analyses,
                default_title=step.id,
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
        return analysis.save()

    def analysis_summaries(
        self,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> ProjectAnalysisPage:
        """Load a bounded history page without fetching publication bodies."""

        return self._analyses.summaries(limit=limit, before=before)

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        return self._analyses.published_analysis(selector)

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        run_id = run_handle_id(run)
        self._control.run_detail(run_id)
        return RunHandle(session=self, id=run_id)

    def resolve_config(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        return self._config.resolve(config)

    def prepare(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> PreparedLabExperiment:
        invocation = _experiment_invocation(experiment)
        resolved_config, config_source = self._config.resolve_with_source(config)
        return PreparedLabExperiment(
            lab=self,
            invocation=invocation,
            config=resolved_config,
            config_source=config_source,
        )

    def preview(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        point: PreviewPoint = "first",
        coordinates: Mapping[str, object] | None = None,
        coordinate_mode: PreviewCoordinateMode = "exact",
        inspection_query: CompiledProgramInspectionQuery | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        """Preview an experiment without requiring an explicit prepare step."""

        return self.prepare(experiment, config=config).preview(
            point=point,
            coordinates=coordinates,
            coordinate_mode=coordinate_mode,
            inspection_query=inspection_query,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        """Run an experiment directly; use ``prepare`` when reusing a config."""

        return self.prepare(experiment, config=config).run(
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def review(
        self,
        experiment: ExperimentSpec,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentReviewHandle:
        """Open a live GUI backed by this process's pure compiler."""

        return self.prepare(experiment, config=config).review(
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def preview_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        point: PreviewPoint = "first",
        coordinates: Mapping[str, object] | None = None,
        coordinate_mode: PreviewCoordinateMode = "exact",
        inspection_query: CompiledProgramInspectionQuery | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self._runner.preview(
            invocation,
            config=config,
            point=point,
            coordinates=coordinates,
            coordinate_mode=coordinate_mode,
            inspection_query=inspection_query,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def execute_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        config_source: RunConfigSource | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
        submission_id: str | None = None,
    ) -> RunHandle:
        manifest = self._runner.run(
            invocation,
            config=config,
            config_source=config_source,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
            submission_id=submission_id,
        )
        return RunHandle(session=self, id=manifest.run_id)

    def review_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentReviewHandle:
        return self._runner.review(
            invocation,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )


def _experiment_invocation(experiment: ExperimentSpec) -> ExperimentInvocation:
    return experiment.bind() if isinstance(experiment, Experiment) else experiment


__all__ = [
    "ExperimentReviewHandle",
    "LabClient",
    "PreparedLabExperiment",
]
