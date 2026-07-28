"""Process-safe requests implemented by instrument drivers."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    OperationRef,
    PropertyRef,
)

type _NonEmptyId = Annotated[str, Field(min_length=1)]


class _DriverRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriverPropertyWrite(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    property_id: _NonEmptyId
    value: StateValue

    @property
    def target(self) -> PropertyRef:
        return PropertyRef(
            self.interface_id,
            self.component_path,
            self.property_id,
        )


class DriverApplyRequest(_DriverRequestModel):
    assignments: tuple[DriverPropertyWrite, ...] = Field(min_length=1)


class DriverOperationArgument(_DriverRequestModel):
    id: _NonEmptyId
    value: StateValue


class DriverPayload(_DriverRequestModel):
    """Opaque codec output materialized before entering a driver."""

    id: _NonEmptyId
    schema_id: _NonEmptyId
    codec_id: _NonEmptyId
    codec_version: int = Field(ge=1)
    media_type: _NonEmptyId
    content: bytes = Field(repr=False)


class DriverInvokeRequest(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    operation_id: _NonEmptyId
    arguments: tuple[DriverOperationArgument, ...] = ()
    payloads: dict[str, DriverPayload] = Field(default_factory=dict)

    @property
    def target(self) -> OperationRef:
        return OperationRef(
            self.interface_id,
            self.component_path,
            self.operation_id,
        )


class DriverCollectResult(_DriverRequestModel):
    request_id: _NonEmptyId
    result_id: _NonEmptyId


class DriverCollectRequest(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    acquisition_id: _NonEmptyId
    results: tuple[DriverCollectResult, ...] = Field(min_length=1)

    @property
    def target(self) -> AcquisitionRef:
        return AcquisitionRef(
            self.interface_id,
            self.component_path,
            self.acquisition_id,
        )

    def result_target(self, result: DriverCollectResult) -> AcquisitionResultRef:
        return self.target.result(result.result_id)


__all__ = [
    "DriverApplyRequest",
    "DriverCollectRequest",
    "DriverCollectResult",
    "DriverInvokeRequest",
    "DriverOperationArgument",
    "DriverPayload",
    "DriverPropertyWrite",
]
