"""Process-safe requests implemented by instrument drivers."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import StateValue
from scopecat.records.artifact import CommandPayload

type _NonEmptyId = Annotated[str, Field(min_length=1)]


class _DriverRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriverPropertyWrite(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    property_id: _NonEmptyId
    value: StateValue


class DriverApplyRequest(_DriverRequestModel):
    assignments: tuple[DriverPropertyWrite, ...] = Field(min_length=1)


class DriverOperationArgument(_DriverRequestModel):
    id: _NonEmptyId
    value: StateValue


class DriverInvokeRequest(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    operation_id: _NonEmptyId
    arguments: tuple[DriverOperationArgument, ...] = ()
    payloads: dict[str, CommandPayload] = Field(default_factory=dict)


class DriverCollectResult(_DriverRequestModel):
    request_id: _NonEmptyId
    result_id: _NonEmptyId


class DriverCollectRequest(_DriverRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    acquisition_id: _NonEmptyId
    results: tuple[DriverCollectResult, ...] = Field(min_length=1)


__all__ = [
    "DriverApplyRequest",
    "DriverCollectRequest",
    "DriverCollectResult",
    "DriverInvokeRequest",
    "DriverOperationArgument",
    "DriverPropertyWrite",
]
