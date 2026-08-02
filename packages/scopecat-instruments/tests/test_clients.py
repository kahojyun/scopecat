from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Mapping
from typing import assert_type, cast

import pytest
from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    OperationArgumentValue,
)
from scopecat.authoring import QuantityType, ScalarType, coordinate
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    ApplyReceipt,
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    compile_interface,
    declared_interface_layout,
    state_projection_assignments,
)

import scopecat_instruments.clients as client_module
from scopecat_instruments import (
    DCMonitorPatch,
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceObservation,
    DCSourcePatch,
    NetworkSweepClient,
    NetworkSweepPatch,
    RFOutputClient,
    RFOutputPatch,
    TemperatureReadoutClient,
    TemperatureReadoutObservation,
    dc_source,
    dc_source_monitor,
    network_sweep,
    rf_output,
    temperature_readout,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutInterface,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE,
    DC_SOURCE_CURRENT,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
    RF_OUTPUT,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
)
from scopecat_instruments.states import (
    TemperatureReadoutObservation as StateTemperatureReadoutObservation,
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


class _ApplyChannel:
    def __init__(self) -> None:
        self.receipt = ApplyReceipt(metadata={"generated": "state-client"})
        self.invoke_receipt = InvokeReceipt(metadata={"generated": "operation-client"})
        self.values: Mapping[PropertyRef, StateLiteral | StateValue] | None = None
        self.operation: OperationRef | None = None
        self.arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = (
            None
        )
        self.instrument_id: str | None = None

    def apply(
        self,
        values: Mapping[PropertyRef, StateLiteral | StateValue],
        *,
        instrument_id: str,
    ) -> ApplyReceipt:
        self.values = values
        self.instrument_id = instrument_id
        return self.receipt

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
        return self.invoke_receipt


def _dc_source_snapshot(*, source_mode: str) -> InstrumentStateSnapshot:
    return InstrumentStateSnapshot(
        instrument_id="flux-source",
        properties=[
            InstrumentPropertyState(
                interface_id=DC_SOURCE.interface_id,
                property_id=DC_SOURCE_MODE.property_id,
                value=StateValue(source_mode),
            )
        ],
    )


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
    rf = rf_output("drive-source")
    vna = network_sweep("readout-vna")
    thermometer = temperature_readout("thermometer")

    assert_type(source, InstrumentRef[DCSourceClient])
    assert_type(rf, InstrumentRef[RFOutputClient])
    assert_type(vna, InstrumentRef[NetworkSweepClient])
    assert_type(thermometer, InstrumentRef[TemperatureReadoutClient])
    assert source.instrument_id == "flux-source"
    assert rf.instrument_id == "drive-source"
    assert vna.instrument_id == "readout-vna"
    assert source.requires == (DC_SOURCE,)
    assert rf.requires == (RF_OUTPUT,)
    assert vna.requires == (NETWORK_SWEEP,)
    assert thermometer.requires == (TEMPERATURE_READOUT,)


def test_generated_dc_source_live_client_applies_flat_state() -> None:
    channel = _ApplyChannel()
    client = DCSourceClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    receipt = assert_type(
        client.apply(
            DCSourcePatch(
                voltage_protection=Quantity(2.0, "V"),
                current_protection=Quantity(10.0, "mA"),
                output_enabled=True,
            )
        ),
        ApplyReceipt,
    )

    assert receipt is channel.receipt
    assert channel.instrument_id == "flux-source"
    assert channel.values == {
        DC_SOURCE_VOLTAGE_PROTECTION: Quantity(2.0, "V"),
        DC_SOURCE_CURRENT_PROTECTION: Quantity(10.0, "mA"),
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_generated_dc_source_live_client_invokes_typed_mode_transitions() -> None:
    channel = _ApplyChannel()
    client = DCSourceClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    receipt = assert_type(
        client.source_voltage(
            range=Quantity(1.0, "V"),
            level=Quantity(0.05, "V"),
        ),
        InvokeReceipt,
    )

    assert receipt is channel.invoke_receipt
    assert channel.instrument_id == "flux-source"
    assert channel.operation == DC_SOURCE_VOLTAGE
    assert channel.arguments == {
        DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: Quantity(0.05, "V"),
    }

    client.source_current(
        range=Quantity(10.0, "mA"),
        level=Quantity(2.0, "mA"),
    )

    assert channel.operation == DC_SOURCE_CURRENT
    assert channel.arguments == {
        DC_SOURCE_CURRENT_RANGE: Quantity(10.0, "mA"),
        DC_SOURCE_CURRENT_LEVEL: Quantity(2.0, "mA"),
    }


def test_generated_rf_live_client_lowers_declared_state() -> None:
    channel = _ApplyChannel()
    client = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "drive-source",
    )

    receipt = assert_type(
        client.apply(
            frequency=Quantity(5.0, "GHz"),
            power=Quantity(-20.0, "dBm"),
            output_enabled=True,
        ),
        ApplyReceipt,
    )

    assert receipt is channel.receipt
    assert channel.instrument_id == "drive-source"
    assert channel.values == {
        RF_OUTPUT_FREQUENCY: Quantity(5.0, "GHz"),
        RF_OUTPUT_POWER: Quantity(-20.0, "dBm"),
        RF_OUTPUT_ENABLED: True,
    }


def test_generated_rf_live_client_rejects_symbolic_state_before_io() -> None:
    channel = _ApplyChannel()
    client = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "drive-source",
    )
    frequency = coordinate(
        "drive_frequency",
        ScalarType(QuantityType(unit="GHz")),
    )

    with pytest.raises(
        TypeError,
        match="direct instrument patch must contain concrete values",
    ):
        client.apply(
            RFOutputPatch(frequency=cast("Quantity", cast("object", frequency)))
        )

    assert channel.values is None
    assert channel.instrument_id is None


def test_dc_source_observation_decodes_the_read_only_mode() -> None:
    channel = _ObservationChannel(
        _dc_source_snapshot(source_mode="voltage"),
        _dc_source_snapshot(source_mode="current"),
    )
    client = DCSourceClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    assert assert_type(client.observation(), DCSourceObservation) == (
        DCSourceObservation(source_mode="voltage")
    )
    assert assert_type(client.refresh_observation(), DCSourceObservation) == (
        DCSourceObservation(source_mode="current")
    )


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
    assert TemperatureReadoutObservation is StateTemperatureReadoutObservation
    layout = declared_interface_layout(compile_interface(TemperatureReadoutInterface))
    assert layout.observed_state is not None
    assert [field.ref for field in layout.observed_state.fields] == [
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    ]


def test_client_module_exports_only_client_owned_types() -> None:
    assert "SymbolicInstrumentRecorder" in client_module.__all__
    assert "TemperatureReadoutObservation" not in client_module.__all__


def test_live_dc_source_factories_expose_explicit_capabilities() -> None:
    source_only = dc_source("source-only")
    source = dc_source_monitor("flux-source")

    assert_type(source_only, InstrumentRef[DCSourceClient])
    assert_type(source, InstrumentRef[DCSourceMonitorClient])
    assert source_only.client_factory is DCSourceClient
    assert source.client_factory is DCSourceMonitorClient
    assert source_only.requires == (DC_SOURCE,)
    assert source.requires == (DC_SOURCE, DC_MONITOR)


def test_generated_live_dc_monitor_applies_monitor_state() -> None:
    channel = _ApplyChannel()
    client = DCSourceMonitorClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    receipt = assert_type(
        client.apply(DCMonitorPatch(measurement_enabled=True)),
        ApplyReceipt,
    )

    assert receipt is channel.receipt
    assert channel.values == {DC_MONITOR_MEASUREMENT_ENABLED: True}


def test_dc_source_patch_only_projects_persistent_controls() -> None:
    state = DCSourcePatch(
        voltage_protection=Quantity(2.0, "V"),
        current_protection=Quantity(10.0, "mA"),
        output_enabled=True,
    )

    assert state_projection_assignments(state) == {
        DC_SOURCE_VOLTAGE_PROTECTION: Quantity(2.0, "V"),
        DC_SOURCE_CURRENT_PROTECTION: Quantity(10.0, "mA"),
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_state_omits_unspecified_properties() -> None:
    assert state_projection_assignments(DCSourcePatch(output_enabled=False)) == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert state_projection_assignments(
        NetworkSweepPatch(
            start_frequency=Quantity(4.8, "GHz"),
            points=401,
            s_parameter="S21",
        )
    ) == {
        NETWORK_SWEEP_START_FREQUENCY: Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }
