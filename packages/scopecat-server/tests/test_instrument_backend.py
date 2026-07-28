from __future__ import annotations

from typing import override

import pytest
from scopecat.records.config import instrument_bindings
from scopecat.sdk.instruments import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverPropertyWrite,
    InstrumentBackend,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from tests.testkit.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    number_state,
)
from tests.testkit.payload_codecs import json_payload_codecs

from scopecat_server.instrument_backend import (
    InstrumentBackendRejected,
    InstrumentBackendUnavailable,
    InstrumentHandleInvalid,
    LocalInstrumentBackendEndpoint,
)


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
        DriverApplyRequest(
            assignments=(
                DriverPropertyWrite(
                    interface_id="test.set_gain/v1",
                    property_id="gain",
                    value=number_state(2.0),
                ),
            )
        ),
    )
    state = endpoint.read_state(connection.handle)
    assert state.properties[0].value == number_state(2.0)
    receipt = endpoint.collect(
        connection.handle,
        DriverCollectRequest(
            interface_id="test.scalar_signal/v1",
            acquisition_id="sample",
            results=(DriverCollectResult(request_id="signal", result_id="signal"),),
        ),
    )
    assert receipt.readback is not None
    assert set(receipt.readback.values) == {"signal"}

    endpoint.disconnect(connection.handle)
    assert provider.drivers[0].disconnect_count == 1
    with pytest.raises(InstrumentHandleInvalid, match="stale"):
        endpoint.read_state(connection.handle)


def test_local_backend_rejects_foreign_handles_and_changed_contracts() -> None:
    provider = _Provider()
    backend = InstrumentBackend(provider=provider)
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
        other.read_state(connection.handle)
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


def test_local_backend_shutdown_disconnects_handles_and_fences_new_work() -> None:
    provider = _Provider()
    endpoint = LocalInstrumentBackendEndpoint(InstrumentBackend(provider=provider))
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
