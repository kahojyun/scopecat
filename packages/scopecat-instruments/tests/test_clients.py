from __future__ import annotations

from typing import assert_type

from scopecat.api._instruments import InstrumentRef
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import declared_state_assignments

from scopecat_instruments import (
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepClient,
    NetworkSweepState,
    dc_source,
    network_sweep,
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
)


def test_first_party_factories_retain_static_client_types() -> None:
    source = dc_source("flux-source")
    vna = network_sweep("readout-vna")

    assert_type(source, InstrumentRef[DCSourceClient])
    assert_type(vna, InstrumentRef[NetworkSweepClient])
    assert source.instrument_id == "flux-source"
    assert vna.instrument_id == "readout-vna"
    assert source.requires == (DC_SOURCE,)
    assert vna.requires == (NETWORK_SWEEP,)


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
