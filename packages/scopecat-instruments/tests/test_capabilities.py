from __future__ import annotations

import pytest

from scopecat_instruments import (
    DC_OUTPUT,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    ScriptedTransport,
    YokogawaGS200,
)


@pytest.mark.parametrize(
    ("driver", "capability_id"),
    [
        (RohdeSchwarzSGS100A("rf", ScriptedTransport([])), RF_OUTPUT),
        (YokogawaGS200("dc", ScriptedTransport([])), DC_OUTPUT),
        (LakeShore372("temperature", ScriptedTransport([])), TEMPERATURE_READOUT),
        (KeysightE5080B("vna", ScriptedTransport([])), NETWORK_SWEEP),
    ],
)
def test_capability_contract_has_complete_ui_metadata(
    driver: (RohdeSchwarzSGS100A | YokogawaGS200 | LakeShore372 | KeysightE5080B),
    capability_id: str,
) -> None:
    description = driver.describe()
    assert description.label
    assert description.description
    assert len(description.capabilities) == 1
    capability = description.capabilities[0]
    assert capability.id == capability_id
    assert capability.label
    assert capability.description
    for field in capability.fields:
        assert field.label
        assert field.description
        assert field.access in {"read_only", "write_only", "read_write"}
    for product in capability.products:
        assert product.label
        assert product.description
        for axis in product.axes:
            assert axis.label
            assert axis.description


@pytest.mark.parametrize(
    "driver",
    [
        RohdeSchwarzSGS100A("rf", ScriptedTransport([])),
        YokogawaGS200("dc", ScriptedTransport([])),
        LakeShore372("temperature", ScriptedTransport([])),
        KeysightE5080B("vna", ScriptedTransport([])),
    ],
)
def test_real_driver_cleanup_does_not_issue_scpi(
    driver: (RohdeSchwarzSGS100A | YokogawaGS200 | LakeShore372 | KeysightE5080B),
) -> None:
    driver.cleanup()
    transport = driver.transport
    assert isinstance(transport, ScriptedTransport)
    transport.assert_complete()
