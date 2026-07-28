from __future__ import annotations

import pytest

from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.interfaces import (
    DC_MONITOR,
    DC_SOURCE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
    dc_source_interface,
)
from scopecat_instruments.testing import ScriptedTransport
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld


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
    interface_id: str,
) -> None:
    description = driver.describe()
    assert description.label
    assert description.description
    interface = next(item for item in description.interfaces if item.id == interface_id)
    assert interface.id == interface_id
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

    assert [item.id for item in without_monitor.interfaces] == [DC_SOURCE]
    assert [item.id for item in with_monitor.interfaces] == [
        DC_SOURCE,
        DC_MONITOR,
    ]
    assert without_monitor.interfaces[0] == dc_source_interface()
    assert with_monitor.interfaces[0] == dc_source_interface()


def test_virtual_dc_source_exposes_source_and_monitor_interfaces() -> None:
    description = VirtualDcSource("dc", VirtualLabWorld(seed=1)).describe()

    assert [item.id for item in description.interfaces] == [
        DC_SOURCE,
        DC_MONITOR,
    ]


def test_dc_source_state_partitions_properties_by_source_mode() -> None:
    state = dc_source_interface().state

    assert state is not None
    assert state.discriminator_property_id == "source_mode"
    assert state.common_property_ids == [
        "voltage_protection",
        "current_protection",
        "output_enabled",
    ]
    assert [(case.value, case.property_ids) for case in state.cases] == [
        ("voltage", ["voltage_range", "voltage_level"]),
        ("current", ["current_range", "current_level"]),
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
