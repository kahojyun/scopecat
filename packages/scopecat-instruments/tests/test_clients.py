from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Mapping
from typing import assert_type, cast

import pytest
from scopecat.api._instruments import InstrumentClientChannel, InstrumentRef
from scopecat.authoring import QuantityType, ScalarType, coordinate
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import ApplyReceipt, PropertyRef
from scopecat.sdk.instruments.declarations import (
    declared_interface_layout,
    declared_state_assignments,
)

from scopecat_instruments import (
    DCMonitorState,
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepClient,
    NetworkSweepState,
    RFOutputClient,
    RFOutputState,
    TemperatureReadoutClient,
    TemperatureReadoutObservation,
    dc_source,
    network_sweep,
    rf_output,
    temperature_readout,
)
from scopecat_instruments._generated_clients import (
    DCSourceClient as GeneratedDCSourceClient,
)
from scopecat_instruments.interface_declarations import (
    TEMPERATURE_READOUT_DECLARATION,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutObservation as DeclaredTemperatureReadoutObservation,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
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
        self.values: Mapping[PropertyRef, StateLiteral | StateValue] | None = None
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


def test_dc_source_live_client_and_monitor_subclass_share_generated_base() -> None:
    assert DCSourceClient is GeneratedDCSourceClient
    assert DCSourceMonitorClient.__bases__ == (GeneratedDCSourceClient,)


def test_generated_dc_source_live_client_applies_discriminated_state() -> None:
    channel = _ApplyChannel()
    client = DCSourceClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    receipt = assert_type(
        client.apply(
            DCSourceVoltage(
                range=Quantity(1.0, "V"),
                level=Quantity(0.05, "V"),
                output_enabled=True,
            )
        ),
        ApplyReceipt,
    )

    assert receipt is channel.receipt
    assert channel.instrument_id == "flux-source"
    assert channel.values == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: Quantity(0.05, "V"),
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_generated_rf_live_client_lowers_declared_state() -> None:
    channel = _ApplyChannel()
    client = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "drive-source",
    )

    receipt = assert_type(
        client.apply(
            RFOutputState(
                frequency=Quantity(5.0, "GHz"),
                power=Quantity(-20.0, "dBm"),
                output_enabled=True,
            )
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
        match="direct instrument state must contain concrete values",
    ):
        client.apply(RFOutputState(frequency=frequency))

    assert channel.values is None
    assert channel.instrument_id is None


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
    layout = declared_interface_layout(TEMPERATURE_READOUT_DECLARATION)
    assert layout.observed_state is not None
    assert [field.ref for field in layout.observed_state.fields] == [
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    ]


def test_live_dc_monitor_selection_requires_the_combined_capability() -> None:
    source = dc_source("flux-source", monitor=True)

    assert_type(source, InstrumentRef[DCSourceMonitorClient])
    assert source.requires == (DC_SOURCE, DC_MONITOR)


def test_live_dc_monitor_subclass_still_applies_monitor_state() -> None:
    channel = _ApplyChannel()
    client = DCSourceMonitorClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    receipt = assert_type(
        client.apply(DCMonitorState(measurement_enabled=True)),
        ApplyReceipt,
    )

    assert receipt is channel.receipt
    assert channel.values == {DC_MONITOR_MEASUREMENT_ENABLED: True}


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
