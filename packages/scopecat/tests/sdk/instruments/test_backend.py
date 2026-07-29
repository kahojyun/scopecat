from __future__ import annotations

from dataclasses import FrozenInstanceError

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
    DriverInvokeArgument,
    DriverInvokeRequest,
    DriverOperationArgument,
    DriverPayloadArgument,
    DriverPropertyWrite,
    DriverScalarValue,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InterfaceRef,
    InvokeCommand,
    OperationArgumentRef,
)
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
    decode_driver_invoke_request,
    lower_backend_invoke_request,
    lower_driver_apply_request,
    lower_driver_collect_request,
)
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry


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
    assert request.assignments[0].target == InterfaceRef("test.dc_source/v1").component(
        "channel-a"
    ).property("level")
    assert "target" not in request.assignments[0].model_dump()
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

    materialized = BackendPayload(
        id=payload.id,
        schema_id=payload.schema_id,
        codec_id=payload.codec_id,
        codec_version=payload.codec_version,
        media_type=payload.media_type,
        content=payload.inline_bytes(),
    )
    backend_request = lower_backend_invoke_request(
        command,
        materialized_payloads={payload.id: materialized},
    )

    assert backend_request.interface_id == "test.pulse_player/v1"
    assert backend_request.component_path == ("channel-a",)
    assert backend_request.operation_id == "play"
    assert backend_request.arguments == (
        BackendOperationArgument(
            id="program",
            value=StateValue(PayloadRef(payload_id=payload.id)),
        ),
    )
    assert backend_request.payloads == {payload.id: materialized}
    assert backend_request.payloads[payload.id].content == b"\x00\xffprogram"
    assert {
        "body",
        "content_hash",
        "size_bytes",
    }.isdisjoint(type(backend_request.payloads[payload.id]).model_fields)
    assert {
        "command_id",
        "instrument_id",
        "resource_id",
        "entity_ids",
        "channel_bindings",
    }.isdisjoint(backend_request.model_dump())
    assert (
        BackendInvokeRequest.model_validate(backend_request.model_dump())
        == backend_request
    )

    decoded_content: list[bytes] = []

    def decode_program(content: bytes) -> object:
        decoded_content.append(content)
        return {"program": content}

    request = decode_driver_invoke_request(
        backend_request,
        PayloadCodecRegistry(
            {
                payload.schema_id: PayloadCodec(
                    id=payload.codec_id,
                    version=payload.codec_version,
                    media_type=payload.media_type,
                    encoder=lambda _value: b"",
                    decoder=decode_program,
                )
            }
        ),
    )

    assert request.target == InterfaceRef("test.pulse_player/v1").component(
        "channel-a"
    ).operation("play")
    assert request.arguments == (
        DriverPayloadArgument(
            id="program",
            schema_id=payload.schema_id,
            value={"program": b"\x00\xffprogram"},
        ),
    )
    assert request.argument_target(request.arguments[0]) == OperationArgumentRef(
        "test.pulse_player/v1",
        ("channel-a",),
        "play",
        "program",
    )
    assert decoded_content == [b"\x00\xffprogram"]
    assert not hasattr(request, "payloads")


def test_driver_invoke_decode_materializes_each_payload_id_once() -> None:
    payload = BackendPayload(
        id="program-a",
        schema_id="test.pulse_program/v1",
        codec_id="test.binary",
        codec_version=1,
        media_type="application/octet-stream",
        content=b"program",
    )
    request = BackendInvokeRequest(
        interface_id="test.pulse_player/v1",
        operation_id="play",
        arguments=(
            BackendOperationArgument(id="wait", value=StateValue(0.25)),
            BackendOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            ),
            BackendOperationArgument(
                id="mirror",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            ),
        ),
        payloads={payload.id: payload},
    )
    decoded: list[bytes] = []

    def decode_program(content: bytes) -> object:
        decoded.append(content)
        return {"content": content}

    driver_request = decode_driver_invoke_request(
        request,
        PayloadCodecRegistry(
            {
                payload.schema_id: PayloadCodec(
                    id=payload.codec_id,
                    version=payload.codec_version,
                    media_type=payload.media_type,
                    encoder=lambda _value: b"",
                    decoder=decode_program,
                )
            }
        ),
    )

    assert driver_request.arguments[0] == DriverOperationArgument(
        id="wait",
        value=0.25,
    )
    program = driver_request.arguments[1]
    mirror = driver_request.arguments[2]
    assert isinstance(program, DriverPayloadArgument)
    assert isinstance(mirror, DriverPayloadArgument)
    assert program.schema_id == payload.schema_id
    assert program.value is mirror.value
    assert decoded == [payload.content]


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
    acquisition = (
        InterfaceRef("test.network_sweep/v1").component("trace-a").acquisition("sweep")
    )
    assert request.target == acquisition
    assert request.result_target(request.results[0]) == acquisition.result("frequency")
    assert request.result_target(request.results[1]) == acquisition.result(
        "s_parameter"
    )
    assert "target" not in request.model_dump()
    restored = DriverCollectRequest.model_validate_json(request.model_dump_json())

    assert restored == request


@pytest.mark.parametrize(
    "request_model",
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
        BackendInvokeRequest(
            interface_id="test.pulse_player/v1",
            operation_id="play",
        ),
        BackendOperationArgument(id="wait", value=StateValue(1.0)),
        BackendPayload(
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
def test_process_safe_request_models_are_frozen_and_closed(
    request_model: BaseModel,
) -> None:
    with pytest.raises(ValidationError, match="Instance is frozen"):
        request_model.__setattr__(
            next(iter(type(request_model).model_fields)),
            None,
        )

    wire = request_model.model_dump()
    wire["command_id"] = "daemon-owned"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(request_model).model_validate(wire)


@pytest.mark.parametrize(
    "driver_request",
    [
        DriverOperationArgument(id="wait", value=1.0),
        DriverPayloadArgument(
            id="program",
            schema_id="test.program/v1",
            value=object(),
        ),
        DriverInvokeRequest(
            interface_id="test.pulse_player/v1",
            operation_id="play",
        ),
    ],
)
def test_worker_local_driver_requests_are_frozen_dataclasses(
    driver_request: object,
) -> None:
    with pytest.raises(FrozenInstanceError):
        driver_request.__setattr__("operation_id", "other")


def test_driver_backend_contracts_are_public_from_sdk_facade() -> None:
    owners = {
        "DriverApplyRequest": DriverApplyRequest,
        "DriverCollectRequest": DriverCollectRequest,
        "DriverCollectResult": DriverCollectResult,
        "DriverInvokeArgument": DriverInvokeArgument,
        "DriverInvokeRequest": DriverInvokeRequest,
        "DriverOperationArgument": DriverOperationArgument,
        "DriverPayloadArgument": DriverPayloadArgument,
        "DriverPropertyWrite": DriverPropertyWrite,
        "DriverScalarValue": DriverScalarValue,
    }

    for name, owner in owners.items():
        assert getattr(instrument_sdk, name) is owner

    for internal_name in (
        "BackendInvokeRequest",
        "BackendOperationArgument",
        "BackendPayload",
        "decode_driver_invoke_request",
        "lower_backend_invoke_request",
        "lower_driver_apply_request",
        "lower_driver_collect_request",
    ):
        with pytest.raises(AttributeError):
            getattr(instrument_sdk, internal_name)
