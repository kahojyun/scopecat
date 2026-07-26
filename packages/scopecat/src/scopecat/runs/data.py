"""Run data and artifact access result models."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from scopecat.kernel.json_types import JsonValue
from scopecat.measurements.results import MeasurementDataset
from scopecat.records.artifact import RunContentEntry


class _RunDataResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class RunArtifactTextResult(_RunDataResult):
    artifact: RunContentEntry
    content: str


class RunArtifactJsonResult(_RunDataResult):
    artifact: RunContentEntry
    content: dict[str, JsonValue]


class RunRecordJsonResult(_RunDataResult):
    record: RunContentEntry
    content: dict[str, JsonValue]


@dataclass(frozen=True)
class RunArtifactBytesResult:
    artifact: RunContentEntry
    content: bytes


class RunMeasurementDatasetResult(_RunDataResult):
    dataset_entry: RunContentEntry
    dataset: MeasurementDataset
