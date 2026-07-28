from __future__ import annotations

from typing import cast

import pytest
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    ComponentRef,
    ComponentSpec,
    InterfaceRef,
    InterfaceSpec,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
    acquisition_results,
)

import scopecat_instruments.members as member_catalog
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
)
from scopecat_instruments.testing import ScriptedTransport
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld


def test_member_catalog_resolves_against_the_interface_contracts() -> None:
    interfaces = {
        interface.id: interface
        for interface in (
            rf_output_interface(),
            dc_source_interface(),
            dc_monitor_interface(),
            temperature_readout_interface(),
            network_sweep_interface(),
        )
    }

    for name in member_catalog.__all__:
        member = cast("object", getattr(member_catalog, name))
        assert isinstance(
            member,
            (
                InterfaceRef,
                ComponentRef,
                PropertyRef,
                OperationRef,
                OperationArgumentRef,
                AcquisitionRef,
                AcquisitionResultRef,
            ),
        )
        interface = interfaces[member.interface_id]
        if isinstance(member, InterfaceRef):
            assert interface.id == member.interface_id
            continue
        component = _resolve_component(interface, member.component_path)
        assert component is not None
        if isinstance(member, ComponentRef):
            continue
        if isinstance(member, PropertyRef):
            assert member.property_id in {item.id for item in component.properties}
            continue
        if isinstance(member, OperationRef):
            assert member.operation_id in {item.id for item in component.operations}
            continue
        if isinstance(member, OperationArgumentRef):
            operation = next(
                item for item in component.operations if item.id == member.operation_id
            )
            assert member.argument_id in {item.id for item in operation.arguments}
            continue
        acquisition_id = member.acquisition_id
        acquisition = next(
            item for item in component.acquisitions if item.id == acquisition_id
        )
        if isinstance(member, AcquisitionRef):
            continue
        assert isinstance(member, AcquisitionResultRef)
        assert member.result_id in {
            result.id for result in acquisition_results(acquisition)
        }


def _resolve_component(
    interface: InterfaceSpec,
    component_path: tuple[str, ...],
) -> InterfaceSpec | ComponentSpec | None:
    selected: InterfaceSpec | ComponentSpec = interface
    for component_id in component_path:
        nested = next(
            (item for item in selected.components if item.id == component_id),
            None,
        )
        if nested is None:
            return None
        selected = nested
    return selected


@pytest.mark.parametrize(
    ("driver", "interface_id"),
    [
        (RohdeSchwarzSGS100A("rf", ScriptedTransport([])), RF_OUTPUT),
        (YokogawaGS200("dc", ScriptedTransport([])), DC_SOURCE),
        (
            YokogawaGS200(
                "dc-monitor",
                ScriptedTransport([]),
                monitor_option=True,
            ),
            DC_MONITOR,
        ),
        (LakeShore372("temperature", ScriptedTransport([])), TEMPERATURE_READOUT),
        (KeysightE5080B("vna", ScriptedTransport([])), NETWORK_SWEEP),
    ],
)
def test_interface_contract_has_complete_ui_metadata(
    driver: (RohdeSchwarzSGS100A | YokogawaGS200 | LakeShore372 | KeysightE5080B),
    interface_id: InterfaceRef,
) -> None:
    description = driver.describe()
    assert description.label
    assert description.description
    interface = next(
        item for item in description.interfaces if item.id == interface_id.interface_id
    )
    assert interface.id == interface_id.interface_id
    assert interface.label
    assert interface.description
    for property_spec in interface.properties:
        assert property_spec.label
        assert property_spec.description
        assert property_spec.access in {"read_only", "write_only", "read_write"}
    for acquisition_spec in interface.acquisitions:
        assert acquisition_spec.label
        assert acquisition_spec.description
        for result in acquisition_results(acquisition_spec):
            assert result.label
            assert result.description
            for axis in result.axes:
                assert axis.label
                assert axis.description


def test_gs200_monitor_option_adds_an_interface_without_changing_dc_source() -> None:
    without_monitor = YokogawaGS200("dc", ScriptedTransport([])).describe()
    with_monitor = YokogawaGS200(
        "dc",
        ScriptedTransport([]),
        monitor_option=True,
    ).describe()

    assert [item.id for item in without_monitor.interfaces] == [DC_SOURCE.interface_id]
    assert [item.id for item in with_monitor.interfaces] == [
        DC_SOURCE.interface_id,
        DC_MONITOR.interface_id,
    ]
    assert without_monitor.interfaces[0] == dc_source_interface()
    assert with_monitor.interfaces[0] == dc_source_interface()


def test_virtual_dc_source_exposes_source_and_monitor_interfaces() -> None:
    description = VirtualDcSource("dc", VirtualLabWorld(seed=1)).describe()

    assert [item.id for item in description.interfaces] == [
        DC_SOURCE.interface_id,
        DC_MONITOR.interface_id,
    ]


def test_dc_source_state_partitions_properties_by_source_mode() -> None:
    state = dc_source_interface().state

    assert state is not None
    assert state.discriminator_property_id == DC_SOURCE_MODE.property_id
    assert state.common_property_ids == [
        DC_SOURCE_VOLTAGE_PROTECTION.property_id,
        DC_SOURCE_CURRENT_PROTECTION.property_id,
        DC_SOURCE_OUTPUT_ENABLED.property_id,
    ]
    assert [(case.value, case.property_ids) for case in state.cases] == [
        (
            "voltage",
            [
                DC_SOURCE_VOLTAGE_RANGE.property_id,
                DC_SOURCE_VOLTAGE_LEVEL.property_id,
            ],
        ),
        (
            "current",
            [
                DC_SOURCE_CURRENT_RANGE.property_id,
                DC_SOURCE_CURRENT_LEVEL.property_id,
            ],
        ),
    ]


def test_dc_monitor_results_follow_the_source_mode() -> None:
    [monitor] = dc_monitor_interface().acquisitions

    assert monitor.kind == "state_discriminated"
    assert monitor.id == DC_MONITOR_ACQUISITION.acquisition_id
    assert monitor.discriminator.interface_id == DC_SOURCE_MODE.interface_id
    assert monitor.discriminator.component_path == []
    assert monitor.discriminator.property_id == DC_SOURCE_MODE.property_id
    assert [
        (case.value, [result.id for result in case.results]) for case in monitor.cases
    ] == [
        ("voltage", [DC_MONITOR_CURRENT_RESULT.result_id]),
        ("current", [DC_MONITOR_VOLTAGE_RESULT.result_id]),
    ]


@pytest.mark.parametrize(
    "driver",
    [
        RohdeSchwarzSGS100A("rf", ScriptedTransport([])),
        YokogawaGS200("dc", ScriptedTransport([])),
        LakeShore372("temperature", ScriptedTransport([])),
        KeysightE5080B("vna", ScriptedTransport([])),
    ],
)
def test_real_driver_disconnect_closes_transport_without_scpi(
    driver: (RohdeSchwarzSGS100A | YokogawaGS200 | LakeShore372 | KeysightE5080B),
) -> None:
    driver.disconnect()
    transport = driver.transport
    assert isinstance(transport, ScriptedTransport)
    assert transport.closed
    transport.assert_complete()
