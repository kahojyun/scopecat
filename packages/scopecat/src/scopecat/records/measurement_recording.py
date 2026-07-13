"""Durable chunks and receipts for point-canonical measurement recording."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.records.measurement import MeasurementRecord

_MAX_RECORD_REF_LENGTH = 512
_DURABLE_RECORD_REF = re.compile(
    r"[A-Za-z][A-Za-z0-9._-]*/(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*"
)
_FORBIDDEN_RECORD_REF_NAMESPACES = frozenset({"data", "inline", "javascript"})


class MeasurementRecordChunk(BaseModel):
    """One idempotently writable projected record with complete identity."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.measurement_record_chunk.v1"] = (
        "scopecat.measurement_record_chunk.v1"
    )
    run_id: str
    dataset_id: str
    recording_contract_fingerprint: str
    logical_point_id: str
    point_index: int = Field(ge=0)
    record: MeasurementRecord

    @field_validator(
        "run_id",
        "dataset_id",
        "recording_contract_fingerprint",
        "logical_point_id",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "measurement record chunk identity fields must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("point_index", mode="before")
    @classmethod
    def validate_point_index(cls, value: object) -> object:
        if isinstance(value, bool):
            msg = "measurement record chunk point index must be an integer"
            raise ValueError(msg)
        return value

    @field_validator("record", mode="before")
    @classmethod
    def snapshot_record(cls, value: object) -> MeasurementRecord:
        if not isinstance(value, MeasurementRecord):
            return MeasurementRecord.model_validate(value)
        return value.model_copy(deep=True)

    @model_validator(mode="after")
    def validate_record_identity(self) -> MeasurementRecordChunk:
        if self.record.run_id != self.run_id:
            msg = "measurement record chunk and record run ids must match"
            raise ValueError(msg)
        if self.record.point_index != self.point_index:
            msg = "measurement record chunk and record point indices must match"
            raise ValueError(msg)
        if self.record.metadata.get("logical_point_id") != self.logical_point_id:
            msg = "measurement record chunk logical point does not match its record"
            raise ValueError(msg)
        return self

    @property
    def operation_id(self) -> str:
        digest = stable_content_hash(
            {
                "schema": "scopecat.measurement_record_operation.v1",
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "recording_contract_fingerprint": self.recording_contract_fingerprint,
                "logical_point_id": self.logical_point_id,
                "point_index": self.point_index,
            }
        )
        return f"measurement-record:{digest}"

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class MeasurementRecordReceipt(BaseModel):
    """Durable committer evidence for one exact measurement record chunk."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.measurement_record_receipt.v1"] = (
        "scopecat.measurement_record_receipt.v1"
    )
    operation_id: str
    chunk_content_hash: str
    record_ref: str

    @field_validator("operation_id", "chunk_content_hash")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "measurement record receipt fields must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("record_ref")
    @classmethod
    def validate_record_ref(cls, value: str) -> str:
        if not value or len(value) > _MAX_RECORD_REF_LENGTH:
            msg = "measurement record receipt ref has an invalid length"
            raise ValueError(msg)
        namespace, separator, _key = value.partition("/")
        if (
            not separator
            or namespace.lower() in _FORBIDDEN_RECORD_REF_NAMESPACES
            or _DURABLE_RECORD_REF.fullmatch(value) is None
        ):
            msg = (
                "measurement record receipt ref must be a safe namespaced "
                "relative durable locator"
            )
            raise ValueError(msg)
        return value

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


__all__ = ["MeasurementRecordChunk", "MeasurementRecordReceipt"]
