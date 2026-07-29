"""Worker-local requests implemented by instrument drivers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    OperationArgumentRef,
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


type DriverScalarValue = bool | int | float | str | Quantity


@dataclass(frozen=True, slots=True)
class DriverOperationArgument:
    id: str
    value: DriverScalarValue


@dataclass(frozen=True, slots=True)
class DriverPayloadArgument:
    """One payload argument decoded inside its driver worker."""

    id: str
    schema_id: str
    value: object = field(repr=False)


type DriverInvokeArgument = DriverOperationArgument | DriverPayloadArgument


@dataclass(frozen=True, slots=True)
class DriverInvokeRequest:
    interface_id: InterfaceId
    operation_id: str
    component_path: tuple[str, ...] = ()
    arguments: tuple[DriverInvokeArgument, ...] = ()

    @property
    def target(self) -> OperationRef:
        return OperationRef(
            self.interface_id,
            self.component_path,
            self.operation_id,
        )

    def argument_target(
        self,
        argument: DriverInvokeArgument,
    ) -> OperationArgumentRef:
        return self.target.argument(argument.id)


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
    "DriverInvokeArgument",
    "DriverInvokeRequest",
    "DriverOperationArgument",
    "DriverPayloadArgument",
    "DriverPropertyWrite",
    "DriverScalarValue",
]
