"""Instrument backend composition and public-command lowering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.sdk.instruments.driver import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverInvokeRequest,
    DriverOperationArgument,
    DriverPropertyWrite,
)
from scopecat.sdk.payloads import PayloadCodecRegistry

if TYPE_CHECKING:
    from scopecat.sdk.instruments.contracts import (
        CollectCommand,
        InstrumentProvider,
        InstrumentStateCommand,
        InvokeCommand,
    )


@dataclass(frozen=True, slots=True)
class InstrumentBackend:
    """Keep one provider and its driver-side payload codecs process-long."""

    provider: InstrumentProvider
    payload_codecs: PayloadCodecRegistry = field(default_factory=PayloadCodecRegistry)


def lower_driver_apply_request(
    command: InstrumentStateCommand,
) -> DriverApplyRequest:
    return DriverApplyRequest(
        assignments=tuple(
            DriverPropertyWrite(
                interface_id=assignment.interface_id,
                component_path=tuple(assignment.component_path),
                property_id=assignment.property_id,
                value=assignment.value,
            )
            for assignment in command.assignments
        )
    )


def lower_driver_invoke_request(command: InvokeCommand) -> DriverInvokeRequest:
    return DriverInvokeRequest(
        interface_id=command.interface_id,
        component_path=tuple(command.component_path),
        operation_id=command.operation_id,
        arguments=tuple(
            DriverOperationArgument(id=argument.id, value=argument.value)
            for argument in command.arguments
        ),
        payloads=dict(command.payloads),
    )


def lower_driver_collect_request(command: CollectCommand) -> DriverCollectRequest:
    target = command.requests[0]
    return DriverCollectRequest(
        interface_id=target.interface_id,
        component_path=tuple(target.component_path),
        acquisition_id=target.acquisition_id,
        results=tuple(
            DriverCollectResult(
                request_id=request.id,
                result_id=request.result_id,
            )
            for request in command.requests
        ),
    )


__all__ = [
    "DriverApplyRequest",
    "DriverCollectRequest",
    "DriverCollectResult",
    "DriverInvokeRequest",
    "DriverOperationArgument",
    "DriverPropertyWrite",
    "InstrumentBackend",
    "lower_driver_apply_request",
    "lower_driver_collect_request",
    "lower_driver_invoke_request",
]
