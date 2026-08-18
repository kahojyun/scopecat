"""Run data and artifact access result models."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from scopecat.kernel.json_types import JsonValue
from scopecat.records.content import ContentEntry
from scopecat.records.measurement import MeasurementDataset


class _RunDataResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class RunArtifactTextResult(_RunDataResult):
    artifact: ContentEntry
    content: str


class RunArtifactJsonResult(_RunDataResult):
    artifact: ContentEntry
    content: dict[str, JsonValue]


class RunRecordJsonResult(_RunDataResult):
    record: ContentEntry
    content: dict[str, JsonValue]


@dataclass(frozen=True)
class RunArtifactBytesResult:
    artifact: ContentEntry
    content: bytes


@dataclass(frozen=True)
class RunDatasetBytesResult:
    dataset: ContentEntry
    content: bytes


class RunMeasurementDatasetResult(_RunDataResult):
    """Internal dataset-loading payload wrapped by the public run facade."""

    dataset_entry: ContentEntry
    dataset: MeasurementDataset
