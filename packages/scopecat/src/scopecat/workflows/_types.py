"""Shared workflow API models and protocols."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from scopecat.authoring import ExperimentDraft, ResolvedExperiment
from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryConfigSourceProvenance,
    ConfigRegistryEntry,
    ConfigRegistryRegistrationJob,
)
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import (
    DryRunSnapshot,
    ExperimentSpec,
    PlanSnapshot,
)
from scopecat.instruments import NativeRunSnapshot
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.run import RunManifest
from scopecat.results import MeasurementDataset
from scopecat.run_comparison import (
    RunComparisonJob,
    RunComparisonResult,
    RunComparisonReviewRecord,
)
from scopecat.runner import RunnerAdapterRunSnapshot

RunMode = Literal["dry", "native_simulate"]
ExperimentInput = ExperimentSpec | ExperimentDraft
RunSnapshot = DryRunSnapshot | RunnerAdapterRunSnapshot | NativeRunSnapshot
ConfigProfileInput = str | Path | ConfigProfileSnapshot

if TYPE_CHECKING:
    from scopecat.candidate_configs import CandidateConfig
    from scopecat.session_analysis import Analysis, AnalysisStep


def _empty_catalog_options() -> dict[str, object]:
    return {}


class RoutineRunStart(Protocol):
    def __call__(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult: ...


class RoutineRunExecutor(Protocol):
    @property
    def id(self) -> str: ...

    def start(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult: ...


class AnalysisCatalog(Protocol):
    @property
    def catalog_id(self) -> str: ...

    def describe(self) -> AnalysisCatalogDescription: ...

    def analysis_step(
        self,
        context: AnalysisStepCatalogContext,
    ) -> AnalysisStepCatalogResult: ...


@dataclass(frozen=True)
class ConfigSourceResult:
    config: ConfigProfileSnapshot
    provenance: ConfigRegistryConfigSourceProvenance | None = None


@dataclass(frozen=True)
class ValidateConfigProfileResult:
    config: ConfigProfileSnapshot
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class RegisterConfigProfileResult:
    job: ConfigRegistryRegistrationJob
    entry: ConfigRegistryEntry


@dataclass(frozen=True)
class RegisterAndActivateConfigProfileResult:
    job: ConfigRegistryRegistrationJob
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class RegisterAndActivateCandidateConfigResult:
    job: ConfigRegistryRegistrationJob
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class ActivateConfigEntryResult:
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class RollbackConfigRegistryResult:
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class StartRunResult:
    manifest: RunManifest
    snapshot: RunSnapshot
    data_ref: str | None = None
    resolved_experiment: ResolvedExperiment | None = None


@dataclass(frozen=True)
class RunSummaryView:
    manifest: RunManifest


@dataclass(frozen=True)
class RunDetails:
    manifest: RunManifest
    config: ConfigProfileSnapshot
    plan: PlanSnapshot


@dataclass(frozen=True)
class RunArtifactView:
    artifact: Artifact


@dataclass(frozen=True)
class RunArtifactTextResult:
    artifact: Artifact
    content: str


@dataclass(frozen=True)
class RunArtifactJsonResult:
    artifact: Artifact
    content: Any


@dataclass(frozen=True)
class RunArtifactBytesResult:
    artifact: Artifact
    content: bytes


@dataclass(frozen=True)
class RunMeasurementDatasetResult:
    artifact: Artifact
    dataset: MeasurementDataset


@dataclass(frozen=True)
class RunDataTableResult:
    artifact: Artifact
    table: DataTableArtifact


@dataclass(frozen=True)
class RunDataArrayResult:
    artifact: Artifact
    array: DataArrayArtifact


@dataclass(frozen=True)
class AnalysisStepCatalogContext:
    step_id: str
    options: Mapping[str, object] = field(default_factory=_empty_catalog_options)


@dataclass(frozen=True)
class AnalysisStepCatalogResult:
    step: AnalysisStep | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisStepDescription:
    step_id: str
    label: str | None = None
    description: str | None = None
    options: tuple[ProviderOptionDescription, ...] = ()
    input_artifact_kinds: tuple[str, ...] = ()
    output_artifact_kinds: tuple[str, ...] = ()
    parameter_change_kinds: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisCatalogDescription:
    catalog_id: str
    steps: tuple[AnalysisStepDescription, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompareRunsResult:
    job: RunComparisonJob
    result: RunComparisonResult


@dataclass(frozen=True)
class ReviewRunComparisonResult:
    result: RunComparisonResult
    review: RunComparisonReviewRecord


@dataclass(frozen=True)
class CandidateActivationPolicy:
    operator: str
    entry_id: str | None = None
    registered_by: str | None = None
    note: str = ""


@dataclass(frozen=True)
class CalibrationRoutine:
    id: str
    experiment: ExperimentInput
    run_executor: RoutineRunExecutor
    analysis_steps: tuple[AnalysisStep, ...] = ()
    activate_candidate: CandidateActivationPolicy | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationRoutineResult:
    routine_id: str
    run: StartRunResult
    analyses: tuple[Analysis, ...] = ()
    candidate: CandidateConfig | None = None
    activation: RegisterAndActivateCandidateConfigResult | None = None
    active_config: ConfigSourceResult | None = None


@dataclass(frozen=True)
class CalibrationRoutineDescription:
    routine_id: str
    run_executor_id: str
    analysis_steps: tuple[str, ...]
    activates_candidate: bool = False
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
