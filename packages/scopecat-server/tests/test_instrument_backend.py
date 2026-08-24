from __future__ import annotations

from typing import override

import pytest
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.config import instrument_bindings
from scopecat.records.instrument import state_member_target
from scopecat.sdk.instruments import (
    DriverCatalog,
    DriverPayload,
    InstrumentBackend,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InterfaceRef,
)
from scopecat.sdk.instruments.backend import (
    BackendApplyRequest,
    BackendCollectRequest,
    BackendCollectResult,
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
    BackendReadRequest,
    BackendStateMemberWrite,
)
from scopecat.sdk.payloads import (
    EncodedPayloadContent,
    PayloadCodecRegistry,
    byte_payload_codec,
)
from scopecat_testkit.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    number_state,
)
from scopecat_testkit.payload_codecs import json_payload_codecs

from scopecat_server.instruments.backend import (
    InstrumentBackendRejected,
    InstrumentBackendUnavailable,
    InstrumentHandleInvalid,
    LocalInstrumentBackendEndpoint,
)

_GAIN = InterfaceRef("test.set_gain/v1").property("gain")


def _gain_read_request() -> BackendReadRequest:
    return BackendReadRequest(targets=(state_member_target(_GAIN),))


class _TrackingDriver(SignalInstrumentDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.disconnect_count = 0

    @override
    def disconnect(self) -> None:
        self.disconnect_count += 1


class _Provider:
    provider_id = "tests.local-endpoint"

    def __init__(self) -> None:
        self.drivers: list[_TrackingDriver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(_TrackingDriver("source-0").describe(),),
        )

    def connect(self, context: InstrumentConnectionContext) -> _TrackingDriver:
        driver = _TrackingDriver(context.binding.id)
        self.drivers.append(driver)
        return driver


def test_local_backend_owns_driver_behind_opaque_handle() -> None:
    provider = _Provider()
    endpoint = LocalInstrumentBackendEndpoint(
        InstrumentBackend(
            provider=provider,
            driver_catalog=DriverCatalog(provider_id=provider.provider_id),
            payload_codecs=json_payload_codecs("tests.program/v1"),
        )
    )
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments

    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )

    assert not hasattr(connection, "driver")
    assert not hasattr(endpoint, "payload_codecs")
    assert endpoint.payload_catalog.codecs[0].schema_id == "tests.program/v1"
    endpoint.apply_state(
        connection.handle,
        BackendApplyRequest(
            assignments=(
                BackendStateMemberWrite(
                    target=state_member_target(_GAIN),
                    value=number_state(2.0),
                ),
            )
        ),
    )
    state = endpoint.read_state(connection.handle, _gain_read_request())
    assert next(
        item.value
        for item in state.observations
        if item.target == state_member_target(_GAIN)
    ) == number_state(2.0)
    receipt = endpoint.collect(
        connection.handle,
        BackendCollectRequest(
            interface_id="test.scalar_signal/v1",
            acquisition_id="sample",
            results=(BackendCollectResult(request_id="signal", result_id="signal"),),
        ),
    )
    assert receipt.readback is not None
    assert set(receipt.readback.values) == {"signal"}

    endpoint.disconnect(connection.handle)
    assert provider.drivers[0].disconnect_count == 1
    with pytest.raises(InstrumentHandleInvalid, match="stale"):
        endpoint.read_state(connection.handle, _gain_read_request())


def test_local_backend_rejects_a_catalog_for_another_provider() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        InstrumentBackend(
            provider=_Provider(),
            driver_catalog=DriverCatalog(provider_id="tests.other-provider"),
        )


def test_local_backend_rejects_foreign_handles_and_changed_contracts() -> None:
    provider = _Provider()
    backend = InstrumentBackend(
        provider=provider,
        driver_catalog=DriverCatalog(provider_id=provider.provider_id),
    )
    endpoint = LocalInstrumentBackendEndpoint(backend)
    other = LocalInstrumentBackendEndpoint(backend)
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(
        binding=binding,
        expected=expected,
    )

    with pytest.raises(InstrumentHandleInvalid, match="another"):
        other.read_state(connection.handle, _gain_read_request())
    with pytest.raises(InstrumentBackendRejected) as rejected:
        endpoint.connect(
            binding=binding,
            expected=expected.model_copy(update={"implementation_version": "changed"}),
        )
    assert [item.code for item in rejected.value.problems] == [
        "instrument_description_changed"
    ]
    assert provider.drivers[-1].disconnect_count == 1

    endpoint.shutdown()
    other.shutdown()


def test_local_backend_decodes_payloads_before_driver_dispatch() -> None:
    provider = _Provider()
    endpoint = LocalInstrumentBackendEndpoint(
        InstrumentBackend(
            provider=provider,
            driver_catalog=DriverCatalog(provider_id=provider.provider_id),
            payload_codecs=json_payload_codecs("tests.program/v1"),
        )
    )
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(binding=binding, expected=expected)

    receipt = endpoint.invoke(
        connection.handle,
        _backend_invoke_request(b'{"program":1}'),
    )

    assert receipt.status == "invoked"
    [driver_request] = provider.drivers[0].invoked
    [argument] = driver_request.arguments.values()
    assert isinstance(argument, DriverPayload)
    assert argument.schema_id == "tests.program/v1"
    assert argument.value == {"program": 1}
    endpoint.disconnect(connection.handle)


def test_local_backend_rejects_payload_decode_before_driver_dispatch() -> None:
    provider = _Provider()
    endpoint = LocalInstrumentBackendEndpoint(
        InstrumentBackend(
            provider=provider,
            driver_catalog=DriverCatalog(provider_id=provider.provider_id),
            payload_codecs=PayloadCodecRegistry(
                {
                    "tests.program/v1": byte_payload_codec(
                        id="tests.canonical-json",
                        version=1,
                        media_type="application/json",
                        encoder=_unused_encoder,
                        decoder=_reject_decoder,
                    )
                }
            ),
        )
    )
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    connection = endpoint.connect(binding=binding, expected=expected)

    receipt = endpoint.invoke(
        connection.handle,
        _backend_invoke_request(b"invalid"),
    )

    assert receipt.status == "not_invoked"
    assert [item.code for item in receipt.problems] == [
        "instrument_payload_decode_failed"
    ]
    assert provider.drivers[0].invoked == []
    endpoint.disconnect(connection.handle)


def test_local_backend_shutdown_disconnects_handles_and_fences_new_work() -> None:
    provider = _Provider()
    endpoint = LocalInstrumentBackendEndpoint(
        InstrumentBackend(
            provider=provider,
            driver_catalog=DriverCatalog(provider_id=provider.provider_id),
        )
    )
    config = load_config()
    [binding] = instrument_bindings(config)
    [expected] = endpoint.describe((binding,)).instruments
    for _ in range(2):
        endpoint.connect(
            binding=binding,
            expected=expected,
        )

    endpoint.shutdown()
    endpoint.shutdown()

    assert not endpoint.healthy
    assert [driver.disconnect_count for driver in provider.drivers] == [1, 1]
    with pytest.raises(InstrumentBackendUnavailable, match="shut down"):
        endpoint.describe((binding,))
    with pytest.raises(InstrumentBackendUnavailable, match="shut down"):
        endpoint.connect(
            binding=binding,
            expected=expected,
        )


def _backend_invoke_request(content: bytes) -> BackendInvokeRequest:
    payload = BackendPayload(
        id="program",
        schema_id="tests.program/v1",
        codec_id="tests.canonical-json",
        codec_version=1,
        media_type="application/json",
        content_format="bytes",
        content=EncodedPayloadContent.from_bytes(content),
    )
    return BackendInvokeRequest(
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=(
            BackendOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            ),
        ),
        payloads={payload.id: payload},
    )


def _unused_encoder(_value: object) -> bytes:
    return b""


def _reject_decoder(_content: bytes) -> object:
    raise ValueError("invalid test payload")
