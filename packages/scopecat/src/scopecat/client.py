"""Notebook-oriented Scopecat client facade."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Self

from scopecat.authoring import (
    ExperimentDraft,
    ResolvedExperiment,
    resolve_experiment,
    resolve_experiment_with_config,
)
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.instruments.sdk import NativeInstrumentProvider
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.reporting import RunOverview, build_run_overview
from scopecat.run_comparison import RunComparisonReviewState, RunComparisonView
from scopecat.workflows import (
    AcceptProposalWorkflowResult,
    CompareRunsResult,
    ConfigProfileInput,
    ReviewRunComparisonResult,
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    RunMode,
    RunSummaryView,
    StartRunResult,
    accept_proposal,
    compare_runs,
    list_run_artifacts,
    list_run_comparisons,
    list_runs,
    load_run,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_data_array,
    read_run_data_table,
    read_run_measurement_dataset,
    review_run_comparison,
    run_experiment,
)
from scopecat.workflows._types import ExperimentInput

RunRef = str | RunManifest | StartRunResult


@dataclass(frozen=True, kw_only=True)
class Client:
    """Session-scoped convenience API for notebooks and Python scripts."""

    workspace: str | Path
    config: str | ConfigProfileSnapshot = "active"
    config_profile: ConfigProfileInput | None = None
    mode: RunMode = "dry"
    native_instrument_provider: NativeInstrumentProvider | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", Path(self.workspace))

    @classmethod
    def from_profile(
        cls,
        config_profile: ConfigProfileInput,
        *,
        workspace: str | Path,
        mode: RunMode = "dry",
        native_instrument_provider: NativeInstrumentProvider | None = None,
    ) -> Self:
        return cls(
            workspace=workspace,
            config_profile=config_profile,
            mode=mode,
            native_instrument_provider=native_instrument_provider,
        )

    def with_native(
        self,
        provider: NativeInstrumentProvider,
        *,
        mode: RunMode = "native_simulate",
    ) -> Self:
        return replace(
            self,
            mode=mode,
            native_instrument_provider=provider,
        )

    def run(
        self,
        experiment: ExperimentInput,
        *,
        mode: RunMode | None = None,
        config: str | ConfigProfileSnapshot | None = None,
        config_profile: ConfigProfileInput | None = None,
        native_instrument_provider: NativeInstrumentProvider | None = None,
    ) -> StartRunResult:
        return run_experiment(
            experiment,
            workspace=self.workspace,
            config=self.config if config is None else config,
            config_profile=self.config_profile
            if config_profile is None
            else config_profile,
            mode=self.mode if mode is None else mode,
            native_instrument_provider=self.native_instrument_provider
            if native_instrument_provider is None
            else native_instrument_provider,
        )

    def resolve(
        self,
        experiment: ExperimentDraft,
        *,
        config: str | ConfigProfileSnapshot | None = None,
        config_profile: ConfigProfileInput | None = None,
    ) -> ResolvedExperiment:
        effective_config = self.config if config is None else config
        effective_profile = (
            self.config_profile if config_profile is None else config_profile
        )
        if isinstance(effective_config, ConfigProfileSnapshot):
            if effective_profile is not None:
                raise ValidationFailed(
                    [
                        Diagnostic(
                            severity="error",
                            code="conflicting_client_config_source",
                            message="provide either config or config_profile, not both",
                            path="config",
                        )
                    ]
                )
            return resolve_experiment_with_config(
                experiment,
                config=effective_config,
                workspace=self.workspace,
            )
        config_entry = (
            None
            if effective_profile is not None and effective_config == "active"
            else effective_config
        )
        return resolve_experiment(
            experiment,
            workspace=self.workspace,
            config_entry=config_entry,
            config_profile=effective_profile,
        )

    def accept_proposal(
        self,
        run: RunRef,
        selector: str,
        *,
        reviewer: str,
        operator: str,
        entry_id: str | None = None,
        note: str = "",
    ) -> AcceptProposalWorkflowResult:
        return accept_proposal(
            run_id=run_id(run),
            selector=selector,
            workspace=self.workspace,
            reviewer=reviewer,
            operator=operator,
            entry_id=entry_id,
            note=note,
        )

    def compare_runs(
        self,
        baseline: RunRef,
        candidate: RunRef,
        *,
        observable_id: str | None = None,
    ) -> CompareRunsResult:
        return compare_runs(
            baseline_run_id=run_id(baseline),
            candidate_run_id=run_id(candidate),
            workspace=self.workspace,
            observable_id=observable_id,
        )

    def run_comparisons(self, run: RunRef) -> list[RunComparisonView]:
        return list_run_comparisons(
            run_id=run_id(run),
            workspace=self.workspace,
        )

    def review_comparison(
        self,
        run: RunRef,
        selector: str,
        *,
        state: RunComparisonReviewState,
        reviewer: str,
        note: str = "",
    ) -> ReviewRunComparisonResult:
        return review_run_comparison(
            run_id=run_id(run),
            selector=selector,
            workspace=self.workspace,
            state=state,
            reviewer=reviewer,
            note=note,
        )

    def overview(self, run: RunRef) -> RunOverview:
        return build_run_overview(
            run_id=run_id(run),
            workspace=self.workspace,
        )

    def runs(self) -> list[RunSummaryView]:
        return list_runs(workspace=self.workspace)

    def run_details(self, run: RunRef) -> RunDetails:
        return load_run(
            run_id=run_id(run),
            workspace=self.workspace,
        )

    def artifacts(self, run: RunRef, *, kind: str | None = None) -> list[str]:
        return [
            view.artifact.id
            for view in list_run_artifacts(
                run_id=run_id(run),
                workspace=self.workspace,
                kind=kind,
            )
        ]

    def measurements(
        self,
        run: RunRef,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
        )

    def artifact_text(
        self,
        run: RunRef,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run: RunRef,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_bytes(
        self,
        run: RunRef,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        return read_run_artifact_bytes(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def data_table(
        self,
        run: RunRef,
        selector: str,
    ) -> RunDataTableResult:
        return read_run_data_table(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
        )

    def data_array(
        self,
        run: RunRef,
        selector: str,
    ) -> RunDataArrayResult:
        return read_run_data_array(
            run_id=run_id(run),
            workspace=self.workspace,
            selector=selector,
        )


def client(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    mode: RunMode = "dry",
    native_instrument_provider: NativeInstrumentProvider | None = None,
) -> Client:
    return Client(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
        mode=mode,
        native_instrument_provider=native_instrument_provider,
    )


def run_id(run: RunRef) -> str:
    if isinstance(run, str):
        return run
    if isinstance(run, StartRunResult):
        return run.manifest.run_id
    return run.run_id


__all__ = ["Client", "RunRef", "client", "run_id"]
