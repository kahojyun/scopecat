from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Mapping
from typing import Annotated, Protocol, assert_type, cast

from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    OperationArgumentValue,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
)
from scopecat.sdk.instruments.declarations import (
    argument,
    compile_interface,
    declared_operation,
    declared_state_assignments,
    instrument_interface,
    operation,
)

from scopecat_instruments import (
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepClient,
    NetworkSweepState,
    TemperatureReadoutClient,
    TemperatureReadoutObservation,
    dc_source,
    network_sweep,
    temperature_readout,
)
from scopecat_instruments.clients import _InstrumentClient
from scopecat_instruments.interface_declarations import (
    TEMPERATURE_OBSERVATION_DECLARATION,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutObservation as DeclaredTemperatureReadoutObservation,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
)


@instrument_interface("test.first_party_typed_operation/v1")
class _SyntheticOperationInterface(Protocol):
    @operation(id="emit_pulse")
    def emit(
        self,
        count: Annotated[int, argument(id="pulse_count")],
        *,
        label: Annotated[str, argument(id="pulse_label")],
    ) -> None: ...


_SYNTHETIC_OPERATION = declared_operation(
    compile_interface(_SyntheticOperationInterface),
    _SyntheticOperationInterface.emit,
)


class _RecordingInvokeChannel:
    def __init__(self) -> None:
        self.receipt = InvokeReceipt(metadata={"test": "typed-operation"})
        self.operation: OperationRef | None = None
        self.arguments: (
            Mapping[
                OperationArgumentRef,
                OperationArgumentValue,
            ]
            | None
        ) = None
        self.instrument_id: str | None = None

    def invoke(
        self,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = None,
        *,
        instrument_id: str,
    ) -> InvokeReceipt:
        self.operation = operation
        self.arguments = arguments
        self.instrument_id = instrument_id
        return self.receipt


class _SyntheticLiveOperationClient(_InstrumentClient):
    def emit(self, count: int, *, label: str) -> InvokeReceipt:
        return self._invoke_declared(
            _SYNTHETIC_OPERATION,
            count,
            label=label,
        )


class _ObservationChannel:
    def __init__(
        self,
        cached: InstrumentStateSnapshot,
        fresh: InstrumentStateSnapshot,
    ) -> None:
        self.cached = cached
        self.fresh = fresh
        self.observed_requests: list[str] = []
        self.refresh_requests: list[str] = []

    def observed_state(self, instrument_id: str) -> InstrumentStateSnapshot:
        self.observed_requests.append(instrument_id)
        return self.cached

    def read_state(self, instrument_id: str) -> InstrumentStateSnapshot:
        self.refresh_requests.append(instrument_id)
        return self.fresh


def _temperature_snapshot(
    *,
    scan_channel: int,
    autoscan_enabled: bool,
) -> InstrumentStateSnapshot:
    return InstrumentStateSnapshot(
        instrument_id="thermometer",
        properties=[
            InstrumentPropertyState(
                interface_id=TEMPERATURE_READOUT.interface_id,
                property_id=TEMPERATURE_READOUT_SCAN_CHANNEL.property_id,
                value=StateValue(scan_channel),
            ),
            InstrumentPropertyState(
                interface_id=TEMPERATURE_READOUT.interface_id,
                property_id=TEMPERATURE_READOUT_AUTOSCAN_ENABLED.property_id,
                value=StateValue(autoscan_enabled),
            ),
        ],
    )


def test_first_party_factories_retain_static_client_types() -> None:
    source = dc_source("flux-source")
    vna = network_sweep("readout-vna")
    thermometer = temperature_readout("thermometer")

    assert_type(source, InstrumentRef[DCSourceClient])
    assert_type(vna, InstrumentRef[NetworkSweepClient])
    assert_type(thermometer, InstrumentRef[TemperatureReadoutClient])
    assert source.instrument_id == "flux-source"
    assert vna.instrument_id == "readout-vna"
    assert source.requires == (DC_SOURCE,)
    assert vna.requires == (NETWORK_SWEEP,)
    assert thermometer.requires == (TEMPERATURE_READOUT,)


def test_live_declared_operation_lowers_arguments_and_returns_receipt() -> None:
    channel = _RecordingInvokeChannel()
    client = _SyntheticLiveOperationClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "pulse-source",
    )

    receipt = assert_type(client.emit(7, label="calibration"), InvokeReceipt)

    assert receipt is channel.receipt
    assert channel.instrument_id == "pulse-source"
    assert channel.operation == _SYNTHETIC_OPERATION.ref
    assert channel.arguments == {
        _SYNTHETIC_OPERATION.ref.argument("pulse_count"): 7,
        _SYNTHETIC_OPERATION.ref.argument("pulse_label"): "calibration",
    }


def test_temperature_observation_uses_cached_and_fresh_snapshot_paths() -> None:
    channel = _ObservationChannel(
        _temperature_snapshot(scan_channel=3, autoscan_enabled=False),
        _temperature_snapshot(scan_channel=7, autoscan_enabled=True),
    )
    client = TemperatureReadoutClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "thermometer",
    )

    cached = assert_type(client.observation(), TemperatureReadoutObservation)

    assert cached == TemperatureReadoutObservation(
        scan_channel=3,
        autoscan_enabled=False,
    )
    assert channel.observed_requests == ["thermometer"]
    assert channel.refresh_requests == []

    fresh = assert_type(
        client.refresh_observation(),
        TemperatureReadoutObservation,
    )

    assert fresh == TemperatureReadoutObservation(
        scan_channel=7,
        autoscan_enabled=True,
    )
    assert channel.observed_requests == ["thermometer"]
    assert channel.refresh_requests == ["thermometer"]
    raw_cached = assert_type(client.observed_state(), InstrumentStateSnapshot)
    raw_fresh = assert_type(client.refresh(), InstrumentStateSnapshot)
    assert raw_cached is channel.cached
    assert raw_fresh is channel.fresh
    assert channel.observed_requests == ["thermometer", "thermometer"]
    assert channel.refresh_requests == ["thermometer", "thermometer"]


def test_temperature_observation_descriptor_and_top_level_export_are_shared() -> None:
    assert TemperatureReadoutObservation is DeclaredTemperatureReadoutObservation
    assert [field.ref for field in TEMPERATURE_OBSERVATION_DECLARATION.fields] == [
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    ]


def test_live_dc_monitor_selection_requires_the_combined_capability() -> None:
    source = dc_source("flux-source", monitor=True)

    assert_type(source, InstrumentRef[DCSourceMonitorClient])
    assert source.requires == (DC_SOURCE, DC_MONITOR)


def test_voltage_state_is_one_complete_mode_transition() -> None:
    state = DCSourceVoltage(
        range=Quantity(1.0, "V"),
        level=Quantity(0.05, "V"),
        output_enabled=True,
    )

    assert declared_state_assignments(state) == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: Quantity(0.05, "V"),
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_state_omits_unspecified_properties() -> None:
    assert declared_state_assignments(DCSourceState(output_enabled=False)) == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert declared_state_assignments(
        NetworkSweepState(
            start_frequency=Quantity(4.8, "GHz"),
            points=401,
            s_parameter="S21",
        )
    ) == {
        NETWORK_SWEEP_START_FREQUENCY: Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }
