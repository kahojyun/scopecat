"""Atomic durable dataset writes and receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self, override

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.records.measurement import MeasurementDatasetSchema, MeasurementRecord

type _MeasurementDatasetRef = Literal["data/measurement_dataset/raw-measurements"]
CANONICAL_MEASUREMENT_DATASET_REF: _MeasurementDatasetRef = (
    "data/measurement_dataset/raw-measurements"
)


class _FrozenRecordingModel(BaseModel):
    """Validation-preserving copy semantics for immutable recording writes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @override
    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return self
        values: dict[str, object] = {
            name: getattr(self, name) for name in type(self).model_fields
        }
        values.update(update)
        return type(self).model_validate(values)

    @override
    def __copy__(self) -> Self:
        return self

    @override
    def __deepcopy__(self, memo: dict[int, object] | None = None) -> Self:
        if memo is not None:
            memo[id(self)] = self
        return self


class MeasurementDatasetHeader(_FrozenRecordingModel):
    """Canonical schema and recording identity for one run dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    recording_contract_fingerprint: str
    dataset_schema: MeasurementDatasetSchema
    expected_record_count: int = Field(ge=0)

    @field_validator("run_id", "recording_contract_fingerprint")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("measurement dataset header fields must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_point_count(self) -> MeasurementDatasetHeader:
        point = next(
            dimension
            for dimension in self.dataset_schema.dimensions
            if dimension.id == "point"
        )
        if point.size != self.expected_record_count:
            raise ValueError(
                "measurement dataset header expected count must match its point "
                "dimension"
            )
        return self

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_dataset_header_operation.v1",
                "run_id": self.run_id,
            }
        )
        return f"measurement-dataset-header:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementDatasetAppend(_FrozenRecordingModel):
    """One idempotent append to a canonical run dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    header_content_hash: str
    start_index: int = Field(ge=0)
    records: tuple[MeasurementRecord, ...] = Field(min_length=1)

    @field_validator("run_id", "header_content_hash")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "measurement dataset write identity fields must be non-empty"
            )
        return value

    @model_validator(mode="after")
    def validate_record_identity(self) -> MeasurementDatasetAppend:
        if any(record.run_id != self.run_id for record in self.records):
            raise ValueError("measurement dataset append and record run ids must match")
        indices = tuple(record.point_index for record in self.records)
        if indices != tuple(
            range(self.start_index, self.start_index + len(self.records))
        ):
            raise ValueError(
                "measurement dataset append records must be contiguous from start_index"
            )
        logical_ids = tuple(record.logical_point_id for record in self.records)
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError("measurement dataset logical point ids must be unique")
        return self

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_dataset_append_operation.v3",
                "run_id": self.run_id,
                "header_content_hash": self.header_content_hash,
                "start_index": self.start_index,
            }
        )
        return f"measurement-dataset-append:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementDatasetReceipt(_FrozenRecordingModel):
    """Durable evidence for one dataset append or seal operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    dataset_content_hash: str
    dataset_ref: _MeasurementDatasetRef = CANONICAL_MEASUREMENT_DATASET_REF

    @field_validator("operation_id", "dataset_content_hash")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("measurement dataset receipt fields must be non-empty")
        return value


class MeasurementDatasetSeal(_FrozenRecordingModel):
    """Seal one append-only dataset after its admitted point range is complete."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    header_content_hash: str
    point_count: int = Field(ge=0)
    dataset_content_hash: str

    @field_validator(
        "run_id",
        "header_content_hash",
        "dataset_content_hash",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "measurement dataset seal identity fields must be non-empty"
            )
        return value

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_dataset_seal_operation.v3",
                "run_id": self.run_id,
                "header_content_hash": self.header_content_hash,
            }
        )
        return f"measurement-dataset-seal:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


def measurement_dataset_content_hash(
    *,
    header_content_hash: str,
    append_content_hashes: tuple[str, ...],
) -> str:
    """Hash a header and its ordered append identities, independent of IPC bytes."""

    return stable_content_hash(
        {
            "schema": "scopecat.measurement_dataset_content.v2",
            "header_content_hash": header_content_hash,
            "append_content_hashes": append_content_hashes,
        }
    )


__all__ = [
    "CANONICAL_MEASUREMENT_DATASET_REF",
    "MeasurementDatasetAppend",
    "MeasurementDatasetHeader",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "measurement_dataset_content_hash",
]
