from __future__ import annotations

from typing import assert_type

import scopecat as sc
from scopecat.sdk.instruments.declarations import member_projection_assignments

from scopecat_instruments import (
    DCMonitorPatch,
    DCSourceMonitorPatch,
    DCSourceMonitorTarget,
    DCSourcePatch,
    DCSourceTarget,
    NetworkSweepPatch,
    RFOutputPatch,
)
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_PROTECTION,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
)


def test_dc_source_target_accepts_fixed_and_scanned_values() -> None:
    current_protection = sc.coordinate(
        "current_protection",
        sc.QuantityType(unit="A"),
    )
    target = DCSourceTarget(
        voltage_protection=sc.Quantity(2.0, "V"),
        current_protection=current_protection,
        output_enabled=True,
    )

    assert_type(target, DCSourceTarget)
    assert member_projection_assignments(target) == {
        DC_SOURCE_VOLTAGE_PROTECTION: sc.Quantity(2.0, "V"),
        DC_SOURCE_CURRENT_PROTECTION: current_protection,
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_patches_omit_unspecified_properties() -> None:
    assert member_projection_assignments(DCSourcePatch(output_enabled=False)) == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert member_projection_assignments(
        NetworkSweepPatch(
            start_frequency=sc.Quantity(4.8, "GHz"),
            points=401,
            s_parameter="S21",
        )
    ) == {
        NETWORK_SWEEP_START_FREQUENCY: sc.Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }


def test_dc_source_and_monitor_patches_use_the_shared_declaration_codec() -> None:
    assert member_projection_assignments(
        DCSourcePatch(
            voltage_protection=sc.Quantity(2.0, "V"),
            current_protection=sc.Quantity(10.0, "mA"),
        )
    ) == {
        DC_SOURCE_VOLTAGE_PROTECTION: sc.Quantity(2.0, "V"),
        DC_SOURCE_CURRENT_PROTECTION: sc.Quantity(10.0, "mA"),
    }
    assert member_projection_assignments(
        DCMonitorPatch(
            measurement_enabled=True,
            integration_cycles=3,
            measurement_delay=sc.Quantity(10.0, "ms"),
        )
    ) == {
        DC_MONITOR_MEASUREMENT_ENABLED: True,
        DC_MONITOR_INTEGRATION_CYCLES: 3,
        DC_MONITOR_MEASUREMENT_DELAY: sc.Quantity(10.0, "ms"),
    }


def test_composite_projection_spans_constituent_interfaces() -> None:
    target = DCSourceMonitorTarget(
        output_enabled=True,
        measurement_enabled=True,
    )

    assert_type(target, DCSourceMonitorTarget)
    assert member_projection_assignments(target) == {
        DC_SOURCE_OUTPUT_ENABLED: True,
        DC_MONITOR_MEASUREMENT_ENABLED: True,
    }
    assert member_projection_assignments(
        DCSourceMonitorPatch(
            output_enabled=False,
            integration_cycles=5,
        )
    ) == {
        DC_SOURCE_OUTPUT_ENABLED: False,
        DC_MONITOR_INTEGRATION_CYCLES: 5,
    }


def test_every_first_party_patch_assignment_is_writable() -> None:
    patches = (
        DCSourcePatch(output_enabled=False),
        DCSourcePatch(
            voltage_protection=sc.Quantity(1.0, "V"),
            current_protection=sc.Quantity(1.0, "mA"),
        ),
        DCMonitorPatch(measurement_enabled=True),
        RFOutputPatch(output_enabled=False),
        NetworkSweepPatch(points=401),
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

    for patch in patches:
        assignments = member_projection_assignments(patch)
        for property_ref in assignments:
            interface = interfaces[property_ref.interface_id]
            property_spec = next(
                item
                for item in interface.properties
                if item.id == property_ref.property_id
            )
            assert property_spec.access != "read_only"
