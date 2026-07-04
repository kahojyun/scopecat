"""Shared workflow API models and protocols."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.authoring import ExperimentDraft, ResolvedExperiment
from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import (
    ExperimentSpec,
    PlanSnapshot,
)
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.results import MeasurementDataset
from scopecat.run_comparison import (
    RunComparisonResult,
    RunComparisonReviewRecord,
)

ExperimentInput = ExperimentSpec | ExperimentDraft
ConfigProfileInput = str | Path | ConfigProfileSnapshot


@dataclass(frozen=True)
class ResolvedConfig:
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None


@dataclass(frozen=True)
class ValidateConfigProfileResult:
    config: ConfigProfileSnapshot
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class RegisteredConfigActivation:
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class ConfigActivation:
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
    def config_source(self) -> RunConfigSource | None:
        if self.resolved_experiment is None:
            return None
        return self.resolved_experiment.config_source


@dataclass(frozen=True)
class RunDetails:
    manifest: RunManifest
    config: ConfigProfileSnapshot
    plan: PlanSnapshot


@dataclass(frozen=True)
class RunArtifactTextResult:
    artifact: RunArtifactEntry
    content: str


@dataclass(frozen=True)
class RunArtifactJsonResult:
    artifact: RunArtifactEntry
    content: Any


@dataclass(frozen=True)
class RunRecordJsonResult:
    record: RunRecordEntry
    content: Any


@dataclass(frozen=True)
class RunArtifactBytesResult:
    artifact: RunArtifactEntry
    content: bytes


@dataclass(frozen=True)
class RunMeasurementDatasetResult:
    dataset_entry: RunDatasetEntry
    dataset: MeasurementDataset


@dataclass(frozen=True)
class RunDataTableResult:
    dataset_entry: RunDatasetEntry
    table: DataTableArtifact


@dataclass(frozen=True)
class RunDataArrayResult:
    dataset_entry: RunDatasetEntry
    array: DataArrayArtifact


@dataclass(frozen=True)
class ReviewRunComparisonResult:
    result: RunComparisonResult
    review: RunComparisonReviewRecord
