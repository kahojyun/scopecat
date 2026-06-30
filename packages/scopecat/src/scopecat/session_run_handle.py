"""Run facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Protocol

from scopecat.client import Client, RunRef, run_id
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.run import RunManifest
from scopecat.run_comparison import RunComparisonView
from scopecat.runs.access import get_artifact_by_id
from scopecat.session_analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.session_data import Data
from scopecat.workflows import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    StartRunResult,
)

if TYPE_CHECKING:
    from scopecat.authoring import ExperimentDraft, ResolvedExperiment
    from scopecat.session_overview import OverviewHandle


class RunSession(Protocol):
    @property
    def client(self) -> Client: ...

    @property
    def reviewer(self) -> str: ...

    @property
    def operator(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    def overview(self, run: RunHandle | RunRef) -> OverviewHandle: ...

    def preview(
        self,
        experiment: ExperimentDraft,
    ) -> ResolvedExperiment: ...


@dataclass(frozen=True, init=False)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    _manifest: RunManifest
    _result: StartRunResult | None

    def __init__(
        self,
        *,
        session: RunSession,
        result: StartRunResult | None = None,
        manifest: RunManifest | None = None,
    ) -> None:
        selected_manifest = result.manifest if result is not None else manifest
        if selected_manifest is None:
            _raise_diagnostic(
                "run_handle_manifest_missing",
                "run handle requires a run result or manifest",
                "run",
            )
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "_manifest", selected_manifest)
        object.__setattr__(self, "_result", result)

    @property
    def result(self) -> StartRunResult:
        if self._result is None:
            _raise_diagnostic(
                "run_execution_snapshot_not_loaded",
                "run execution snapshot is not loaded for this workspace run handle",
                "run",
            )
        return self._result

    @property
    def id(self) -> str:
        return self.manifest.run_id

    @property
    def manifest(self) -> RunManifest:
        return self._manifest

    @property
    def resolved_experiment(self) -> ResolvedExperiment | None:
        if self._result is None:
            return None
        return self._result.resolved_experiment

    @property
    def data_ref(self) -> str | None:
        if self._result is not None:
            return self._result.data_ref
        artifact = get_artifact_by_id(self.manifest, "raw-measurements")
        return artifact.path if artifact is not None else None

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(self.session.client.artifacts(self.id))

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.session.client.measurements(self.id, selector=selector)

    def data(self) -> Data:
        return Data(run=self)

    def analysis(self, title: str) -> Analysis:
        return Analysis(run=self, title=title)

    def analyze(self, step: AnalysisStep) -> Analysis:
        return step.run(AnalysisContext(run=self, data=self.data()))

    def artifact_text(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return self.session.client.artifact_text(
            self.id,
            selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return self.session.client.artifact_json(
            self.id,
            selector,
            expected_kind=expected_kind,
        )

    def overview(self) -> OverviewHandle:
        return self.session.overview(self)

    def comparisons(self) -> tuple[RunComparisonView, ...]:
        return tuple(self.session.client.run_comparisons(self.id))


def run_handle_id(run: RunHandle | RunRef) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return run_id(run)


def _raise_diagnostic(code: str, message: str, path: str) -> NoReturn:
    raise ValidationFailed(
        [
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                path=path,
            )
        ]
    )


__all__ = ["RunHandle", "RunSession", "run_handle_id"]
