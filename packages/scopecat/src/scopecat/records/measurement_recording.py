"""Atomic durable dataset writes and receipts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.records.measurement import MeasurementRecord

type _MeasurementDatasetRef = Literal["data/measurement_dataset/raw-measurements"]
CANONICAL_MEASUREMENT_DATASET_REF: _MeasurementDatasetRef = (
    "data/measurement_dataset/raw-measurements"
)


class MeasurementDatasetAppend(BaseModel):
    """One idempotent append to a canonical run dataset."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )

    run_id: str
    recording_contract_fingerprint: str
    start_index: int = Field(ge=0)
    records: tuple[MeasurementRecord, ...] = Field(min_length=1)

    @field_validator("run_id", "recording_contract_fingerprint")
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
                "schema": "scopecat.measurement_dataset_append_operation.v2",
                "run_id": self.run_id,
                "recording_contract_fingerprint": self.recording_contract_fingerprint,
                "start_index": self.start_index,
            }
        )
        return f"measurement-dataset-append:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementDatasetReceipt(BaseModel):
    """Durable evidence for one dataset append or seal operation."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )

    operation_id: str
    dataset_content_hash: str
    dataset_ref: _MeasurementDatasetRef = CANONICAL_MEASUREMENT_DATASET_REF

    @field_validator("operation_id", "dataset_content_hash")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("measurement dataset receipt fields must be non-empty")
        return value


class MeasurementDatasetSeal(BaseModel):
    """Seal one append-only dataset after its admitted point range is complete."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )

    run_id: str
    recording_contract_fingerprint: str
    point_count: int = Field(ge=0)
    dataset_content_hash: str

    @field_validator(
        "run_id",
        "recording_contract_fingerprint",
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
                "schema": "scopecat.measurement_dataset_seal_operation.v2",
                "run_id": self.run_id,
                "recording_contract_fingerprint": self.recording_contract_fingerprint,
            }
        )
        return f"measurement-dataset-seal:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


def measurement_dataset_content_hash(
    *,
    recording_contract_fingerprint: str,
    append_content_hashes: tuple[str, ...],
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.measurement_dataset_content.v1",
            "recording_contract_fingerprint": recording_contract_fingerprint,
            "append_content_hashes": append_content_hashes,
        }
    )


__all__ = [
    "CANONICAL_MEASUREMENT_DATASET_REF",
    "MeasurementDatasetAppend",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "measurement_dataset_content_hash",
]
