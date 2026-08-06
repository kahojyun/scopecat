from __future__ import annotations

from typing import cast

import pytest
from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.kernel.value_types import Bool, Int, Quantity, Scalar
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
    StatePropertyRef,
)

import scopecat_instruments.members as member_catalog
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.interfaces import (
    dc_bias_interface,
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASURE_CURRENT,
    DC_MONITOR_MEASURE_VOLTAGE,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_MONITOR_VOLTAGE_RESULT,
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
    RF_OUTPUT,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_RESISTANCE_RESULT,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.testing import ScriptedTransport
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld


def test_member_catalog_resolves_against_the_interface_contracts() -> None:
    interfaces = {
        interface.id: interface
        for interface in (
            rf_output_interface(),
            dc_bias_interface(),
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
        assert member.result_id in {result.id for result in acquisition.results}


def test_network_sweep_axis_size_tracks_the_points_state() -> None:
    [sweep] = network_sweep_interface().acquisitions
    expected = StatePropertyRef(
        interface_id=NETWORK_SWEEP_POINTS.interface_id,
        component_path=list(NETWORK_SWEEP_POINTS.component_path),
        property_id=NETWORK_SWEEP_POINTS.property_id,
    )

    for result in sweep.results:
        [frequency] = result.axes
        assert frequency.size == expected


def test_declared_network_sweep_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(network_sweep_interface()) == (
        "3855d931051bae10b1a7112b85e819a4ce6160d1e2ebc67a828b3f251ca8407f"
    )


def test_declared_rf_output_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(rf_output_interface()) == (
        "2bda603a084e8dbb487b6dea5cecb8be4037e2753eb9a6bd0fcbfabfcbff2dbc"
    )


def test_declared_dc_bias_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(dc_bias_interface()) == (
        "ea7221ffa7a80c9c404850959d7328419867bb5d321900018379b13df3be80b9"
    )


def test_declared_dc_source_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(dc_source_interface()) == (
        "0bd8e9c89a327e53af4c682b71ff8b4f0867faf53850b9260c6f48034e4d2d5b"
    )


def test_declared_dc_monitor_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(dc_monitor_interface()) == (
        "7d5c7a32e96daf82162371174645c75ecdeb6c97e4ded87ab719e0749dad85e0"
    )


def test_declared_temperature_readout_preserves_the_contract_fingerprint() -> None:
    assert model_wire_content_hash(temperature_readout_interface()) == (
        "45e177997076748215dda389754748144ceaedebf1594473a00643ad51568c71"
    )


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
        for result in acquisition_spec.results:
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


def test_temperature_readout_separates_scanner_state_from_samples() -> None:
    interface = temperature_readout_interface()

    properties = {item.id: item for item in interface.properties}
    assert set(properties) == {
        TEMPERATURE_READOUT_SCAN_CHANNEL.property_id,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED.property_id,
    }
    assert properties[
        TEMPERATURE_READOUT_SCAN_CHANNEL.property_id
    ].value_type == Scalar(Int(minimum=1, maximum=9007199254740991))
    assert len(interface.acquisitions) == 1
    assert {item.id for item in interface.acquisitions[0].results} == {
        TEMPERATURE_READOUT_TEMPERATURE_RESULT.result_id,
        TEMPERATURE_READOUT_RESISTANCE_RESULT.result_id,
    }


def test_dc_source_separates_state_observation_and_mode_transitions() -> None:
    interface = dc_source_interface()

    assert interface.id == "scopecat.dc_source/v3"
    assert [item.id for item in interface.properties] == [
        DC_SOURCE_VOLTAGE_PROTECTION.property_id,
        DC_SOURCE_CURRENT_PROTECTION.property_id,
        DC_SOURCE_OUTPUT_ENABLED.property_id,
        DC_SOURCE_MODE.property_id,
    ]
    properties = {item.id: item for item in interface.properties}
    assert properties[DC_SOURCE_MODE.property_id].access == "read_only"
    assert {
        properties[property.property_id].access
        for property in (
            DC_SOURCE_VOLTAGE_PROTECTION,
            DC_SOURCE_CURRENT_PROTECTION,
            DC_SOURCE_OUTPUT_ENABLED,
        )
    } == {"read_write"}

    voltage, current = interface.operations
    assert voltage.id == DC_SOURCE_VOLTAGE.operation_id
    assert [argument.id for argument in voltage.arguments] == [
        DC_SOURCE_VOLTAGE_RANGE.argument_id,
        DC_SOURCE_VOLTAGE_LEVEL.argument_id,
    ]
    assert [argument.value_type for argument in voltage.arguments] == [
        Scalar(Quantity(unit="V")),
        Scalar(Quantity(unit="V")),
    ]
    assert current.id == DC_SOURCE_CURRENT.operation_id
    assert [argument.id for argument in current.arguments] == [
        DC_SOURCE_CURRENT_RANGE.argument_id,
        DC_SOURCE_CURRENT_LEVEL.argument_id,
    ]
    assert [argument.value_type for argument in current.arguments] == [
        Scalar(Quantity(unit="A")),
        Scalar(Quantity(unit="A")),
    ]


def test_dc_monitor_declares_independent_results() -> None:
    monitor_interface = dc_monitor_interface()
    current, voltage = monitor_interface.acquisitions

    assert monitor_interface.id == "scopecat.dc_monitor/v4"
    properties = {item.id: item for item in monitor_interface.properties}
    assert set(properties) == {
        DC_MONITOR_MEASUREMENT_ENABLED.property_id,
        DC_MONITOR_INTEGRATION_CYCLES.property_id,
        DC_MONITOR_MEASUREMENT_DELAY.property_id,
    }
    assert properties[DC_MONITOR_MEASUREMENT_ENABLED.property_id].value_type == Scalar(
        Bool()
    )
    assert properties[DC_MONITOR_INTEGRATION_CYCLES.property_id].value_type == Scalar(
        Int(minimum=1, maximum=9007199254740991)
    )
    assert properties[DC_MONITOR_MEASUREMENT_DELAY.property_id].value_type == Scalar(
        Quantity(unit="s", minimum=0.0)
    )
    assert {item.access for item in properties.values()} == {"read_write"}
    assert [
        (
            acquisition.id,
            [result.id for result in acquisition.results],
        )
        for acquisition in (current, voltage)
    ] == [
        (
            DC_MONITOR_MEASURE_CURRENT.acquisition_id,
            [DC_MONITOR_CURRENT_RESULT.result_id],
        ),
        (
            DC_MONITOR_MEASURE_VOLTAGE.acquisition_id,
            [DC_MONITOR_VOLTAGE_RESULT.result_id],
        ),
    ]
    assert current.preconditions == []
    assert voltage.preconditions == []


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
