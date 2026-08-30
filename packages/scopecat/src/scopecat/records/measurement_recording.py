"""Atomic durable dataset writes and receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Literal, Self, cast, override

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.content_identity import (
    content_fingerprint,
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.records.execution import RecoveryGroupCompletion
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementPartitionedArray,
    MeasurementRecord,
    MeasurementSegmentedArray,
    MeasurementValue,
)

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
    expected_record_count: int | None = Field(default=None, ge=0)
    record_count_limit: int = Field(ge=0)

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
        if (
            self.expected_record_count is not None
            and self.expected_record_count > self.record_count_limit
        ):
            raise ValueError("measurement expected count cannot exceed its limit")
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


class MeasurementDatasetBatch(_FrozenRecordingModel):
    """One contiguous record batch offered to a dataset writer."""

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
    def validate_record_identity(self) -> MeasurementDatasetBatch:
        if any(record.run_id != self.run_id for record in self.records):
            raise ValueError("measurement dataset batch and record run ids must match")
        indices = tuple(record.point_index for record in self.records)
        if indices != tuple(
            range(self.start_index, self.start_index + len(self.records))
        ):
            raise ValueError(
                "measurement dataset batch records must be contiguous from start_index"
            )
        logical_ids = tuple(record.logical_point_id for record in self.records)
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError(
                "measurement dataset batch logical point ids must be unique"
            )
        return self


class MeasurementDatasetAppend(MeasurementDatasetBatch):
    """One idempotent durable append to a canonical run dataset."""

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
        return stable_content_hash(
            {
                "schema": "scopecat.measurement_dataset_append_content.v8",
                "run_id": self.run_id,
                "header_content_hash": self.header_content_hash,
                "start_index": self.start_index,
                "record_content_hashes": self.record_content_hashes,
            }
        )

    @property
    def record_content_hashes(self) -> tuple[str, ...]:
        """Return chunk-neutral identities without serializing array values."""

        return tuple(measurement_record_content_hash(record) for record in self.records)


class MeasurementRecoveryGroupStage(_FrozenRecordingModel):
    """One exact recovery group's non-contiguous measurement records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    header_content_hash: str
    schedule_fingerprint: str
    group_id: str
    records: tuple[MeasurementRecord, ...] = Field(min_length=1)

    @field_validator(
        "run_id",
        "header_content_hash",
        "schedule_fingerprint",
        "group_id",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("measurement recovery stage identity must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_records(self) -> MeasurementRecoveryGroupStage:
        if any(record.run_id != self.run_id for record in self.records):
            raise ValueError("measurement recovery stage and record run ids must match")
        if len(self.point_indices) != len(set(self.point_indices)):
            raise ValueError("measurement recovery stage point indices must be unique")
        logical_ids = tuple(record.logical_point_id for record in self.records)
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError(
                "measurement recovery stage logical point ids must be unique"
            )
        return self

    @property
    def point_indices(self) -> tuple[int, ...]:
        return tuple(record.point_index for record in self.records)

    @property
    def record_content_hashes(self) -> tuple[str, ...]:
        return tuple(measurement_record_content_hash(record) for record in self.records)

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_recovery_stage_operation.v1",
                "run_id": self.run_id,
                "schedule_fingerprint": self.schedule_fingerprint,
                "group_id": self.group_id,
            }
        )
        return f"measurement-recovery-stage:{digest}"

    @property
    def content_hash(self) -> str:
        return stable_content_hash(
            {
                "schema": "scopecat.measurement_recovery_stage_content.v1",
                "run_id": self.run_id,
                "header_content_hash": self.header_content_hash,
                "schedule_fingerprint": self.schedule_fingerprint,
                "group_id": self.group_id,
                "point_indices": self.point_indices,
                "record_content_hashes": self.record_content_hashes,
            }
        )

    @property
    def completion(self) -> RecoveryGroupCompletion:
        return RecoveryGroupCompletion(
            schedule_fingerprint=self.schedule_fingerprint,
            group_id=self.group_id,
            point_indices=self.point_indices,
            output_kind="staged_measurement",
            record_content_hashes=self.record_content_hashes,
        )


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


class MeasurementDatasetFragment(_FrozenRecordingModel):
    """Durable measurement prefix owned by one execution segment."""

    segment_id: str
    run_id: str
    header_content_hash: str
    start_index: int = Field(ge=0)
    record_count: int = Field(ge=0)
    fragment_content_hash: str
    dataset_content_hash: str | None = None

    @field_validator(
        "segment_id",
        "run_id",
        "header_content_hash",
        "fragment_content_hash",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("measurement fragment fields must be non-empty")
        return value

    @property
    def end_index(self) -> int:
        return self.start_index + self.record_count


class MeasurementDatasetSeal(_FrozenRecordingModel):
    """Seal the current fragment and request a run-level dataset identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    header_content_hash: str
    fragment_start_index: int = Field(ge=0)
    point_count: int = Field(ge=0)
    fragment_content_hash: str

    @field_validator(
        "run_id",
        "header_content_hash",
        "fragment_content_hash",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "measurement dataset seal identity fields must be non-empty"
            )
        return value

    @model_validator(mode="after")
    def validate_fragment_range(self) -> MeasurementDatasetSeal:
        if self.fragment_start_index > self.point_count:
            raise ValueError("measurement fragment starts after the sealed prefix")
        return self

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_dataset_seal_operation.v4",
                "run_id": self.run_id,
                "header_content_hash": self.header_content_hash,
                "fragment_start_index": self.fragment_start_index,
            }
        )
        return f"measurement-dataset-seal:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


def measurement_dataset_content_hash(
    *,
    header_content_hash: str,
    record_content_hashes: tuple[str, ...],
) -> str:
    """Hash a header and ordered records, independent of IPC chunk boundaries."""

    return stable_content_hash(
        {
            "schema": "scopecat.measurement_dataset_content.v3",
            "header_content_hash": header_content_hash,
            "record_content_hashes": record_content_hashes,
        }
    )


def measurement_fragment_content_hash(
    *,
    header_content_hash: str,
    start_index: int,
    record_content_hashes: tuple[str, ...],
) -> str:
    """Identify one segment-owned range independently of Arrow chunking."""

    return stable_content_hash(
        {
            "schema": "scopecat.measurement_dataset_fragment_content.v1",
            "header_content_hash": header_content_hash,
            "start_index": start_index,
            "record_content_hashes": record_content_hashes,
        }
    )


def measurement_record_content_hash(record: MeasurementRecord) -> str:
    """Identify one normalized record using buffer fingerprints for arrays."""

    return stable_content_hash(
        {
            "schema": "scopecat.measurement_record_content.v2",
            "record": content_fingerprint(
                {
                    "run_id": record.run_id,
                    "logical_point_id": record.logical_point_id,
                    "point_index": record.point_index,
                    "coordinates": {
                        key: _measurement_value_content_identity(value)
                        for key, value in record.coordinates.items()
                    },
                    "observables": {
                        key: _measurement_value_content_identity(value)
                        for key, value in record.observables.items()
                    },
                    "acquisition_evidence": record.acquisition_evidence,
                    "metadata": record.metadata,
                }
            ),
        }
    )


def _measurement_value_content_identity(value: MeasurementValue) -> object:
    if isinstance(value, MeasurementArray | MeasurementPartitionedArray):
        return _rectangular_array_content_identity(value)
    if isinstance(value, MeasurementSegmentedArray):
        return {
            "kind": value.kind,
            "dtype": value.dtype,
            "unit": value.unit,
            "segments": tuple(
                _measurement_value_content_identity(segment)
                for segment in value.segments
            ),
            "metadata": value.metadata,
        }
    return value


def _rectangular_array_content_identity(
    value: MeasurementArray | MeasurementPartitionedArray,
) -> object:
    availability = value.availability
    return {
        "kind": "rectangular_array",
        "dtype": value.dtype,
        "unit": value.unit,
        "shape": value.shape,
        "values_sha256": _rectangular_array_sha256(value),
        "availability": (
            None
            if availability is None
            else {
                "valid_sha256": hashlib.sha256(
                    memoryview(availability.valid).cast("B")
                ).hexdigest(),
                "unavailable": availability.unavailable,
            }
        ),
        "metadata": value.metadata,
    }


def _rectangular_array_sha256(
    value: MeasurementArray | MeasurementPartitionedArray,
) -> str:
    if isinstance(value, MeasurementArray):
        return hashlib.sha256(memoryview(value.values).cast("B")).hexdigest()
    digest = hashlib.sha256()
    prefix_shape = value.shape[: value.axis]
    prefixes = np.ndindex(prefix_shape) if prefix_shape else ((),)
    for prefix in prefixes:
        for partition in value.partitions:
            selected = cast("NDArray[np.generic]", partition.values[prefix])
            digest.update(memoryview(selected).cast("B"))
    return digest.hexdigest()


__all__ = [
    "CANONICAL_MEASUREMENT_DATASET_REF",
    "MeasurementDatasetAppend",
    "MeasurementDatasetBatch",
    "MeasurementDatasetFragment",
    "MeasurementDatasetHeader",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "MeasurementRecoveryGroupStage",
    "measurement_dataset_content_hash",
    "measurement_fragment_content_hash",
    "measurement_record_content_hash",
]
