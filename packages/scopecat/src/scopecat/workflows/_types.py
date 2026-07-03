"""Shared workflow API models and protocols."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    ExperimentSpec,
    PlanSnapshot,
)
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.run import RunManifest
from scopecat.results import MeasurementDataset
from scopecat.run_comparison import (
    RunComparisonJob,
    RunComparisonResult,
    RunComparisonReviewRecord,
)

ExperimentInput = ExperimentSpec | ExperimentDraft
ConfigProfileInput = str | Path | ConfigProfileSnapshot


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
class ValidateExperimentResult:
    experiment: ExperimentSpec
    config: ConfigProfileSnapshot
    diagnostics: tuple[Diagnostic, ...]
    plan: PlanSnapshot | None = None
    resolved_experiment: ResolvedExperiment | None = None

    @property
    def ok(self) -> bool:
        return not any(
            diagnostic.severity in {"error", "blocker"}
            for diagnostic in self.diagnostics
        )


@dataclass(frozen=True)
class PreviewExperimentResult:
    experiment: ExperimentSpec
    config: ConfigProfileSnapshot
    plan: PlanSnapshot
    diagnostics: tuple[Diagnostic, ...]
    resolved_experiment: ResolvedExperiment | None = None

    @property
    def template_id(self) -> str | None:
        if self.resolved_experiment is None:
            return None
        return self.resolved_experiment.template_id

    @property
    def inputs(self) -> dict[str, object]:
        if self.resolved_experiment is None:
            return {}
        return dict(self.resolved_experiment.inputs)

    @property
    def config_provenance(self) -> ConfigRegistryConfigSourceProvenance | None:
        if self.resolved_experiment is None:
            return None
        return self.resolved_experiment.config_provenance


@dataclass(frozen=True)
class RunDetails:
    manifest: RunManifest
    config: ConfigProfileSnapshot
    plan: PlanSnapshot


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
class CompareRunsResult:
    job: RunComparisonJob
    result: RunComparisonResult


@dataclass(frozen=True)
class ReviewRunComparisonResult:
    result: RunComparisonResult
    review: RunComparisonReviewRecord
