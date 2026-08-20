from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_type, cast

import pytest
from scopecat.api.instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    OperationArgumentValue,
)
from scopecat.authoring import QuantityType, coordinate
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.kernel.value_types import Bool, Int, Scalar
from scopecat.records.instrument import (
    InstrumentStateReadback,
    InstrumentStateSnapshot,
    state_member_ref,
    state_observation,
)
from scopecat.sdk.instruments import (
    ApplyReceipt,
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
    StateMemberRef,
)
from scopecat.sdk.instruments.declarations import (
    compile_interface,
    declared_interface_layout,
    state_projection_assignments,
)

from scopecat_instruments import (
    DCMonitorPatch,
    DCMonitorState,
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceMonitorState,
    DCSourcePatch,
    DCSourceState,
    NetworkSweepClient,
    NetworkSweepPatch,
    RFOutputClient,
    RFOutputPatch,
    TemperatureReadoutClient,
    TemperatureReadoutState,
    dc_source,
    dc_source_monitor,
    network_sweep,
    rf_output,
    temperature_readout,
)
from scopecat_instruments._client_runtime import (
    ClientStateField,
    ClientStateSchema,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutInterface,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
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
    TemperatureReadoutState as CatalogTemperatureReadoutState,
)


class _StateChannel:
    def __init__(
        self,
        cached: InstrumentStateSnapshot,
        fresh: InstrumentStateSnapshot,
    ) -> None:
        self.cached = cached
        self.fresh = fresh
        self.observed_requests: list[str] = []
        self.refresh_requests: list[str] = []
        self.member_requests: list[tuple[str, tuple[StateMemberRef, ...]]] = []

    def observed_state(self, instrument_id: str) -> InstrumentStateSnapshot:
        self.observed_requests.append(instrument_id)
        return self.cached

    def read_state(self, instrument_id: str) -> InstrumentStateSnapshot:
        self.refresh_requests.append(instrument_id)
        return self.fresh

    def read_state_members(
        self,
        instrument_id: str,
        *targets: StateMemberRef,
    ) -> InstrumentStateReadback:
        self.member_requests.append((instrument_id, targets))
        selected = set(targets)
        return InstrumentStateReadback(
            instrument_id=instrument_id,
            observations=[
                observation
                for observation in self.fresh.observations
                if state_member_ref(observation.target) in selected
            ],
        )


@dataclass(frozen=True, slots=True)
class _ReadableState:
    enabled: bool
    channel: int


_READABLE_ENABLED = PropertyRef("test.readable_state/v1", (), "enabled")
_READABLE_CHANNEL = PropertyRef("test.readable_state/v1", (), "channel")
_READABLE_STATE_SCHEMA = ClientStateSchema(
    state_type=_ReadableState,
    fields=(
        ClientStateField("enabled", _READABLE_ENABLED, Scalar(Bool())),
        ClientStateField("channel", _READABLE_CHANNEL, Scalar(Int(minimum=1))),
    ),
)


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
        observations=[
            state_observation(
                DC_SOURCE_VOLTAGE_PROTECTION, StateValue(Quantity(2.0, "V"))
            ),
            state_observation(
                DC_SOURCE_CURRENT_PROTECTION, StateValue(Quantity(10.0, "mA"))
            ),
            state_observation(DC_SOURCE_OUTPUT_ENABLED, StateValue(True)),
            state_observation(DC_SOURCE_MODE, StateValue(source_mode)),
        ],
    )


def _rf_output_snapshot(*, frequency_ghz: float) -> InstrumentStateSnapshot:
    return InstrumentStateSnapshot(
        instrument_id="drive-source",
        observations=[
            state_observation(
                RF_OUTPUT_FREQUENCY,
                StateValue(Quantity(frequency_ghz, "GHz")),
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
        observations=[
            state_observation(
                TEMPERATURE_READOUT_SCAN_CHANNEL, StateValue(scan_channel)
            ),
            state_observation(
                TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
                StateValue(autoscan_enabled),
            ),
        ],
    )


def _dc_source_monitor_snapshot(*, source_mode: str) -> InstrumentStateSnapshot:
    source = _dc_source_snapshot(source_mode=source_mode)
    return InstrumentStateSnapshot(
        instrument_id=source.instrument_id,
        observations=[
            *source.observations,
            state_observation(DC_MONITOR_MEASUREMENT_ENABLED, StateValue(True)),
            state_observation(DC_MONITOR_INTEGRATION_CYCLES, StateValue(2)),
            state_observation(
                DC_MONITOR_MEASUREMENT_DELAY, StateValue(Quantity(0.1, "s"))
            ),
        ],
    )


def test_client_state_schema_decodes_a_complete_readable_snapshot() -> None:
    snapshot = InstrumentStateSnapshot(
        instrument_id="readable",
        observations=[
            state_observation(_READABLE_ENABLED, StateValue(True)),
            state_observation(_READABLE_CHANNEL, StateValue(3)),
        ],
    )

    assert _READABLE_STATE_SCHEMA.decode(snapshot) == _ReadableState(
        enabled=True,
        channel=3,
    )


def test_client_state_schema_rejects_an_incomplete_readable_snapshot() -> None:
    snapshot = InstrumentStateSnapshot(
        instrument_id="readable",
        observations=[state_observation(_READABLE_ENABLED, StateValue(True))],
    )

    with pytest.raises(
        ValueError,
        match="instrument-state snapshot is missing declared fields: channel",
    ):
        _READABLE_STATE_SCHEMA.decode(snapshot)


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


def test_generated_member_client_reads_and_writes_one_property() -> None:
    state_channel = _StateChannel(
        _rf_output_snapshot(frequency_ghz=5.0),
        _rf_output_snapshot(frequency_ghz=6.0),
    )
    client = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", state_channel)),
        "drive-source",
    )

    assert client.frequency.observed() == Quantity(5e9, "Hz")
    assert client.frequency.read() == Quantity(6e9, "Hz")
    assert state_channel.member_requests == [("drive-source", (RF_OUTPUT_FREQUENCY,))]

    apply_channel = _ApplyChannel()
    writable = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", apply_channel)),
        "drive-source",
    )
    assert writable.frequency.set(Quantity(7.0, "GHz")) is apply_channel.receipt
    assert apply_channel.values == {RF_OUTPUT_FREQUENCY: Quantity(7.0, "GHz")}


def test_generated_rf_live_client_rejects_symbolic_state_before_io() -> None:
    channel = _ApplyChannel()
    client = RFOutputClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "drive-source",
    )
    frequency = coordinate(
        "drive_frequency",
        QuantityType(unit="GHz"),
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


def test_dc_source_state_combines_writable_values_and_read_only_mode() -> None:
    channel = _StateChannel(
        _dc_source_snapshot(source_mode="voltage"),
        _dc_source_snapshot(source_mode="current"),
    )
    client = DCSourceClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    assert assert_type(client.state(), DCSourceState) == (
        DCSourceState(
            voltage_protection=Quantity(2.0, "V"),
            current_protection=Quantity(0.01, "A"),
            output_enabled=True,
            source_mode="voltage",
        )
    )
    assert assert_type(client.refresh_state(), DCSourceState) == (
        DCSourceState(
            voltage_protection=Quantity(2.0, "V"),
            current_protection=Quantity(0.01, "A"),
            output_enabled=True,
            source_mode="current",
        )
    )


def test_temperature_state_uses_cached_and_fresh_snapshot_paths() -> None:
    channel = _StateChannel(
        _temperature_snapshot(scan_channel=3, autoscan_enabled=False),
        _temperature_snapshot(scan_channel=7, autoscan_enabled=True),
    )
    client = TemperatureReadoutClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "thermometer",
    )

    cached = assert_type(client.state(), TemperatureReadoutState)

    assert cached == TemperatureReadoutState(
        scan_channel=3,
        autoscan_enabled=False,
    )
    assert channel.observed_requests == ["thermometer"]
    assert channel.refresh_requests == []

    fresh = assert_type(
        client.refresh_state(),
        TemperatureReadoutState,
    )

    assert fresh == TemperatureReadoutState(
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


def test_temperature_state_schema_and_top_level_export_are_shared() -> None:
    assert TemperatureReadoutState is CatalogTemperatureReadoutState
    layout = declared_interface_layout(compile_interface(TemperatureReadoutInterface))
    state = layout.state
    assert state is not None
    assert [field.ref for field in state.fields] == [
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    ]


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


def test_composite_client_returns_state_grouped_by_interface() -> None:
    channel = _StateChannel(
        _dc_source_monitor_snapshot(source_mode="voltage"),
        _dc_source_monitor_snapshot(source_mode="current"),
    )
    client = DCSourceMonitorClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "flux-source",
    )

    state = assert_type(client.state(), DCSourceMonitorState)

    assert state.dc_source.source_mode == "voltage"
    assert state.dc_monitor == DCMonitorState(
        measurement_enabled=True,
        integration_cycles=2,
        measurement_delay=Quantity(0.1, "s"),
    )
    assert client.refresh_state().dc_source.source_mode == "current"


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
