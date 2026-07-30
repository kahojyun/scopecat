from __future__ import annotations

from typing import assert_type

import scopecat as sc

from scopecat_instruments import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
    RFOutputState,
)
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
)
from scopecat_instruments.members import (
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
)


def test_voltage_state_accepts_fixed_and_scanned_desired_values() -> None:
    level = sc.coordinate(
        "dc_bias",
        sc.ScalarType(sc.QuantityType(unit="V")),
    )
    target = DCSourceVoltage(
        range=sc.Quantity(1.0, "V"),
        level=level,
        output_enabled=True,
    )

    assert_type(target, DCSourceVoltage)
    assert target.target_assignments() == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_RANGE: sc.Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: level,
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_states_omit_unspecified_properties() -> None:
    assert DCSourceState(output_enabled=False).target_assignments() == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert NetworkSweepState(
        start_frequency=sc.Quantity(4.8, "GHz"),
        points=401,
        s_parameter="S21",
    ).target_assignments() == {
        NETWORK_SWEEP_START_FREQUENCY: sc.Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }


def test_every_first_party_state_assignment_is_writable() -> None:
    states = (
        DCSourceState(output_enabled=False),
        DCSourceVoltage(
            range=sc.Quantity(1.0, "V"),
            level=sc.Quantity(0.0, "V"),
        ),
        DCSourceCurrent(
            range=sc.Quantity(1.0, "mA"),
            level=sc.Quantity(0.0, "mA"),
        ),
        DCMonitorState(measurement_enabled=True),
        RFOutputState(output_enabled=False),
        NetworkSweepState(points=401),
    )
    interfaces = {
        interface.id: interface
        for interface in (
            dc_source_interface(),
            dc_monitor_interface(),
            rf_output_interface(),
            network_sweep_interface(),
        )
    }

    for state in states:
        for property_ref in state.target_assignments():
            interface = interfaces[property_ref.interface_id]
            property_spec = next(
                item
                for item in interface.properties
                if item.id == property_ref.property_id
            )
            assert property_spec.access != "read_only"
