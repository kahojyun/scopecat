"""Run data and artifact access result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.experiments import ExperimentSpec
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.run import RunManifest
from scopecat.results import MeasurementDataset


@dataclass(frozen=True)
class RunDetails:
    manifest: RunManifest


@dataclass(frozen=True)
class StructuredRunDetails:
    manifest: RunManifest
    config: ConfigProfileSnapshot
    experiment: ExperimentSpec


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


__all__ = [
    "RunArtifactBytesResult",
    "RunArtifactJsonResult",
    "RunArtifactTextResult",
    "RunDataArrayResult",
    "RunDataTableResult",
    "RunDetails",
    "RunMeasurementDatasetResult",
    "RunRecordJsonResult",
    "StructuredRunDetails",
]
