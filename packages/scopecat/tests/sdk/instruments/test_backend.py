from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

import scopecat.sdk.instruments as instrument_sdk
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import command_payload_from_bytes
from scopecat.sdk.instruments import (
    CollectAxisRequest,
    CollectCommand,
    CollectResultRequest,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverInvokeRequest,
    DriverOperationArgument,
    DriverPayload,
    DriverPropertyWrite,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InvokeCommand,
    lower_driver_apply_request,
    lower_driver_collect_request,
    lower_driver_invoke_request,
)


def test_apply_command_lowers_to_driver_property_writes() -> None:
    command = InstrumentStateCommand(
        command_id="apply-1",
        instrument_id="source-1",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-1",
                interface_id="test.dc_source/v1",
                component_path=["channel-a"],
                property_id="level",
                value=StateValue(1.25),
                entity_ids=["logical-source"],
            )
        ],
    )

    request = lower_driver_apply_request(command)

    assert request.model_dump(mode="json") == {
        "assignments": [
            {
                "interface_id": "test.dc_source/v1",
                "component_path": ["channel-a"],
                "property_id": "level",
                "value": 1.25,
            }
        ]
    }
    assert DriverApplyRequest.model_validate_json(request.model_dump_json()) == request


def test_invoke_command_lowers_with_opaque_payload() -> None:
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id="test.pulse_program/v1",
        codec_id="test.binary",
        codec_version=1,
        media_type="application/octet-stream",
        content=b"\x00\xffprogram",
    )
    command = InvokeCommand(
        command_id="invoke-1",
        instrument_id="drive-1",
        resource_id="drive-1",
        interface_id="test.pulse_player/v1",
        component_path=["channel-a"],
        operation_id="play",
        arguments=[
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
        ],
        payloads={payload.id: payload},
        entity_ids=["logical-drive"],
    )

    materialized = DriverPayload(
        id=payload.id,
        schema_id=payload.schema_id,
        codec_id=payload.codec_id,
        codec_version=payload.codec_version,
        media_type=payload.media_type,
        content=payload.inline_bytes(),
    )
    request = lower_driver_invoke_request(
        command,
        materialized_payloads={payload.id: materialized},
    )

    assert request.interface_id == "test.pulse_player/v1"
    assert request.component_path == ("channel-a",)
    assert request.operation_id == "play"
    assert request.arguments == (
        DriverOperationArgument(
            id="program",
            value=StateValue(PayloadRef(payload_id=payload.id)),
        ),
    )
    assert request.payloads == {payload.id: materialized}
    assert request.payloads[payload.id].content == b"\x00\xffprogram"
    assert request.model_dump()["payloads"][payload.id]["content"] == b"\x00\xffprogram"
    assert {
        "body",
        "content_hash",
        "size_bytes",
    }.isdisjoint(type(request.payloads[payload.id]).model_fields)
    assert {
        "command_id",
        "instrument_id",
        "resource_id",
        "entity_ids",
        "channel_bindings",
    }.isdisjoint(request.model_dump())
    assert DriverInvokeRequest.model_validate(request.model_dump()) == request


def test_collect_command_lowers_to_one_acquisition_request() -> None:
    command = CollectCommand(
        command_id="collect-1",
        instrument_id="vna-1",
        point_index=7,
        point_count=20,
        requests=[
            CollectResultRequest(
                id="frequency-axis",
                interface_id="test.network_sweep/v1",
                component_path=["trace-a"],
                acquisition_id="sweep",
                result_id="frequency",
                unit="Hz",
                dimensions=[
                    CollectAxisRequest(
                        id="frequency",
                        kind="frequency",
                        size=401,
                        unit="Hz",
                    )
                ],
                entity_ids=["logical-vna"],
                metadata={"product_id": "frequencies"},
            ),
            CollectResultRequest(
                id="s-parameter-trace",
                interface_id="test.network_sweep/v1",
                component_path=["trace-a"],
                acquisition_id="sweep",
                result_id="s_parameter",
                unit="ratio",
                dtype="complex128",
                dimensions=[
                    CollectAxisRequest(
                        id="frequency",
                        kind="frequency",
                        size=401,
                        unit="Hz",
                    )
                ],
                entity_ids=["logical-vna"],
                metadata={"product_id": "trace"},
            ),
        ],
    )

    request = lower_driver_collect_request(command)

    assert request.model_dump(mode="json") == {
        "interface_id": "test.network_sweep/v1",
        "component_path": ["trace-a"],
        "acquisition_id": "sweep",
        "results": [
            {
                "request_id": "frequency-axis",
                "result_id": "frequency",
            },
            {
                "request_id": "s-parameter-trace",
                "result_id": "s_parameter",
            },
        ],
    }
    restored = DriverCollectRequest.model_validate_json(request.model_dump_json())

    assert restored == request


@pytest.mark.parametrize(
    "backend_request",
    [
        DriverPropertyWrite(
            interface_id="test.dc_source/v1",
            property_id="level",
            value=StateValue(1.0),
        ),
        DriverApplyRequest(
            assignments=(
                DriverPropertyWrite(
                    interface_id="test.dc_source/v1",
                    property_id="level",
                    value=StateValue(1.0),
                ),
            )
        ),
        DriverInvokeRequest(
            interface_id="test.pulse_player/v1",
            operation_id="play",
        ),
        DriverOperationArgument(id="wait", value=StateValue(1.0)),
        DriverPayload(
            id="program",
            schema_id="test.program/v1",
            codec_id="test.binary",
            codec_version=1,
            media_type="application/octet-stream",
            content=b"\x00\xff",
        ),
        DriverCollectResult(request_id="signal", result_id="signal"),
        DriverCollectRequest(
            interface_id="test.signal/v1",
            acquisition_id="sample",
            results=(DriverCollectResult(request_id="signal", result_id="signal"),),
        ),
    ],
)
def test_driver_request_models_are_frozen_and_closed(
    backend_request: BaseModel,
) -> None:
    with pytest.raises(ValidationError, match="Instance is frozen"):
        backend_request.__setattr__(
            next(iter(type(backend_request).model_fields)),
            None,
        )

    wire = backend_request.model_dump()
    wire["command_id"] = "daemon-owned"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(backend_request).model_validate(wire)


def test_driver_backend_contracts_are_public_from_sdk_facade() -> None:
    owners = {
        "DriverApplyRequest": DriverApplyRequest,
        "DriverCollectRequest": DriverCollectRequest,
        "DriverCollectResult": DriverCollectResult,
        "DriverInvokeRequest": DriverInvokeRequest,
        "DriverOperationArgument": DriverOperationArgument,
        "DriverPayload": DriverPayload,
        "DriverPropertyWrite": DriverPropertyWrite,
        "lower_driver_apply_request": lower_driver_apply_request,
        "lower_driver_collect_request": lower_driver_collect_request,
        "lower_driver_invoke_request": lower_driver_invoke_request,
    }

    for name, owner in owners.items():
        assert getattr(instrument_sdk, name) is owner
