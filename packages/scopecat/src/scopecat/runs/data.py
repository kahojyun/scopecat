"""Run data and artifact access result models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.kernel.json_types import JsonValue
from scopecat.measurements.results import MeasurementDataset
from scopecat.records.artifact import RunContentEntry
from scopecat.records.data_artifact import DataArrayArtifact, DataTableArtifact


@dataclass(frozen=True)
class RunArtifactTextResult:
    artifact: RunContentEntry
    content: str


@dataclass(frozen=True)
class RunArtifactJsonResult:
    artifact: RunContentEntry
    content: Mapping[str, JsonValue]


@dataclass(frozen=True)
class RunRecordJsonResult:
    record: RunContentEntry
    content: Mapping[str, JsonValue]


@dataclass(frozen=True)
class RunArtifactBytesResult:
    artifact: RunContentEntry
    content: bytes


@dataclass(frozen=True)
class RunMeasurementDatasetResult:
    dataset_entry: RunContentEntry
    dataset: MeasurementDataset


@dataclass(frozen=True)
class RunDataTableResult:
    dataset_entry: RunContentEntry
    table: DataTableArtifact


@dataclass(frozen=True)
class RunDataArrayResult:
    dataset_entry: RunContentEntry
    array: DataArrayArtifact
