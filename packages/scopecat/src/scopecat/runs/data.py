"""Run data and artifact access result models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.kernel.json_types import JsonValue
from scopecat.measurements.results import MeasurementDataset
from scopecat.records.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.records.data_artifact import DataArrayArtifact, DataTableArtifact


@dataclass(frozen=True)
class RunArtifactTextResult:
    artifact: RunArtifactEntry
    content: str


@dataclass(frozen=True)
class RunArtifactJsonResult:
    artifact: RunArtifactEntry
    content: Mapping[str, JsonValue]


@dataclass(frozen=True)
class RunRecordJsonResult:
    record: RunRecordEntry
    content: Mapping[str, JsonValue]


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
