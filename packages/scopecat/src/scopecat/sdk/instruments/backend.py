"""Process-safe instrument backend requests and worker-local lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.sdk.instruments.authoring import (
    DriverArgument,
    DriverOperation,
    DriverPayload,
)
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    AcquisitionResultRef,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.payloads import PayloadCodecRegistry

if TYPE_CHECKING:
    from scopecat.sdk.instruments.contracts import (
        CollectCommand,
        InstrumentProvider,
        InstrumentStateCommand,
        InvokeCommand,
    )

type _NonEmptyId = Annotated[str, Field(min_length=1)]


class _BackendRequestModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class BackendPropertyWrite(_BackendRequestModel):
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


class BackendApplyRequest(_BackendRequestModel):
    assignments: tuple[BackendPropertyWrite, ...] = Field(min_length=1)


class BackendPayload(_BackendRequestModel):
    """Verified opaque bytes ready to cross a driver-worker boundary."""

    id: _NonEmptyId
    schema_id: _NonEmptyId
    codec_id: _NonEmptyId
    codec_version: int = Field(ge=1)
    media_type: _NonEmptyId
    content: bytes = Field(repr=False)


class BackendOperationArgument(_BackendRequestModel):
    id: _NonEmptyId
    value: StateValue


class BackendInvokeRequest(_BackendRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    operation_id: _NonEmptyId
    arguments: tuple[BackendOperationArgument, ...] = ()
    payloads: dict[str, BackendPayload] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload_bindings(self) -> BackendInvokeRequest:
        argument_ids = tuple(argument.id for argument in self.arguments)
        if len(argument_ids) != len(set(argument_ids)):
            raise ValueError("backend operation argument ids must be unique")
        if any(
            payload_id != payload.id for payload_id, payload in self.payloads.items()
        ):
            raise ValueError("backend payload map keys must match payload ids")
        referenced_ids = {
            value.payload_id
            for argument in self.arguments
            if isinstance((value := argument.value.root), PayloadRef)
        }
        if referenced_ids != set(self.payloads):
            raise ValueError("backend payload bindings must match request arguments")
        return self


class BackendCollectResult(_BackendRequestModel):
    request_id: _NonEmptyId
    result_id: _NonEmptyId


class BackendCollectRequest(_BackendRequestModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyId, ...] = ()
    acquisition_id: _NonEmptyId
    results: tuple[BackendCollectResult, ...] = Field(min_length=1)

    @property
    def target(self) -> AcquisitionRef:
        return AcquisitionRef(
            self.interface_id,
            self.component_path,
            self.acquisition_id,
        )

    def result_target(self, result: BackendCollectResult) -> AcquisitionResultRef:
        return self.target.result(result.result_id)


@dataclass(frozen=True, slots=True)
class InstrumentBackend:
    """Keep one provider and its driver-side payload codecs process-long."""

    provider: InstrumentProvider
    payload_codecs: PayloadCodecRegistry = field(default_factory=PayloadCodecRegistry)


def lower_backend_apply_request(
    command: InstrumentStateCommand,
) -> BackendApplyRequest:
    return BackendApplyRequest(
        assignments=tuple(
            BackendPropertyWrite(
                interface_id=assignment.interface_id,
                component_path=tuple(assignment.component_path),
                property_id=assignment.property_id,
                value=assignment.value,
            )
            for assignment in command.assignments
        )
    )


def lower_backend_invoke_request(
    command: InvokeCommand,
    *,
    materialized_payloads: Mapping[str, BackendPayload],
) -> BackendInvokeRequest:
    return BackendInvokeRequest(
        interface_id=command.interface_id,
        component_path=tuple(command.component_path),
        operation_id=command.operation_id,
        arguments=tuple(
            BackendOperationArgument(id=argument.id, value=argument.value)
            for argument in command.arguments
        ),
        payloads=dict(materialized_payloads),
    )


def decode_driver_operation(
    request: BackendInvokeRequest,
    payload_codecs: PayloadCodecRegistry,
) -> DriverOperation:
    decoded_payloads: dict[str, object] = {}
    arguments: dict[str, DriverArgument] = {}
    for argument in request.arguments:
        value = argument.value.root
        if not isinstance(value, PayloadRef):
            arguments[argument.id] = value
            continue
        payload = request.payloads[value.payload_id]
        if value.payload_id not in decoded_payloads:
            decoded_payloads[value.payload_id] = payload_codecs.decode_content(
                payload,
                payload.content,
            )
        arguments[argument.id] = DriverPayload(
            schema_id=payload.schema_id,
            value=decoded_payloads[value.payload_id],
        )
    return DriverOperation(
        target=OperationRef(
            request.interface_id,
            request.component_path,
            request.operation_id,
        ),
        arguments=arguments,
    )


def lower_backend_collect_request(command: CollectCommand) -> BackendCollectRequest:
    target = command.requests[0]
    return BackendCollectRequest(
        interface_id=target.interface_id,
        component_path=tuple(target.component_path),
        acquisition_id=target.acquisition_id,
        results=tuple(
            BackendCollectResult(
                request_id=request.id,
                result_id=request.result_id,
            )
            for request in command.requests
        ),
    )


__all__ = [
    "BackendApplyRequest",
    "BackendCollectRequest",
    "BackendCollectResult",
    "BackendInvokeRequest",
    "BackendOperationArgument",
    "BackendPayload",
    "BackendPropertyWrite",
    "InstrumentBackend",
    "decode_driver_operation",
    "lower_backend_apply_request",
    "lower_backend_collect_request",
    "lower_backend_invoke_request",
]
