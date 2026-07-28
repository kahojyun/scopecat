from __future__ import annotations

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectResultRequest,
    InstrumentStateAssignment,
    InstrumentStateCommand,
)

from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    YokogawaGS200,
)
from scopecat_instruments.interfaces import (
    DC_SOURCE,
    NETWORK_SWEEP,
    TEMPERATURE_READOUT,
)
from scopecat_instruments.testing import ScriptedTransport
from scopecat_instruments.transport import TransportError
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld


class _FailingTransport:
    def write(self, command: str) -> None:
        raise TransportError(f"failed write: {command}")

    def query(self, command: str) -> str:
        raise TransportError(f"failed query: {command}")

    def close(self) -> None:
        pass


def test_read_only_lakeshore_command_is_not_applied_without_io() -> None:
    driver = LakeShore372("fridge", ScriptedTransport([]))
    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="fridge",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="fridge",
                    interface_id=TEMPERATURE_READOUT,
                    property_id="heater_range",
                    value=StateValue(1),
                )
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_read_only_property"


def test_invalid_gs200_mode_is_not_applied_without_io() -> None:
    driver = YokogawaGS200("bias", ScriptedTransport([]))
    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="bias",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="bias",
                    interface_id=DC_SOURCE,
                    property_id="source_mode",
                    value=StateValue(17),
                )
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_property_value_mismatch"


def test_real_gs200_rejects_mixed_state_cases_without_io() -> None:
    transport = ScriptedTransport([])
    driver = YokogawaGS200("bias", transport)

    receipt = driver.apply_state(_mixed_dc_mode_command())

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_mixed_state_cases"
    assert transport.transcript == []


def test_real_gs200_rejects_explicit_state_case_mismatch_without_io() -> None:
    transport = ScriptedTransport([])
    driver = YokogawaGS200("bias", transport)
    command = InstrumentStateCommand(
        instrument_id="bias",
        assignments=[
            InstrumentStateAssignment(
                resource_id="bias",
                interface_id=DC_SOURCE,
                property_id="source_mode",
                value=StateValue("current"),
            ),
            InstrumentStateAssignment(
                resource_id="bias",
                interface_id=DC_SOURCE,
                property_id="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            ),
        ],
    )

    receipt = driver.apply_state(command)

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_state_case_mismatch"
    assert transport.transcript == []


def test_virtual_dc_rejects_mixed_state_cases_without_mutation() -> None:
    world = VirtualLabWorld(seed=3)
    driver = VirtualDcSource("bias", world)
    before = world.dc_source("bias")
    before_values = (
        before.source_mode,
        before.voltage_level_v,
        before.current_level_a,
    )

    receipt = driver.apply_state(_mixed_dc_mode_command())
    after = world.dc_source("bias")

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_mixed_state_cases"
    assert (
        after.source_mode,
        after.voltage_level_v,
        after.current_level_a,
    ) == before_values


def test_virtual_dc_requires_explicit_discriminator_to_switch_cases() -> None:
    world = VirtualLabWorld(seed=3)
    driver = VirtualDcSource("bias", world)

    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="bias",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="bias",
                    interface_id=DC_SOURCE,
                    property_id="current_level",
                    value=StateValue(Quantity(1.0e-3, "A")),
                )
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_state_case_mismatch"
    source = world.dc_source("bias")
    assert source.source_mode == "voltage"
    assert source.current_level_a == 0.0


def test_gs200_baseline_transport_loss_is_raised() -> None:
    driver = YokogawaGS200("bias", _FailingTransport())

    with pytest.raises(TransportError, match="failed query"):
        driver.apply_state(InstrumentStateCommand(instrument_id="bias"))


def test_apply_transport_loss_reports_unknown_not_not_applied() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.apply_state(InstrumentStateCommand(instrument_id="vna"))

    assert receipt.status == "unknown"
    assert receipt.problems[0].code == "instrument_apply_outcome_unknown"


def test_unsupported_collect_result_is_not_collected_without_trigger() -> None:
    driver = KeysightE5080B("vna", ScriptedTransport([]))
    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="not_a_trace",
                    interface_id=NETWORK_SWEEP,
                    acquisition_id="sweep",
                    result_id="not_a_trace",
                )
            ],
        )
    )

    assert receipt.status == "not_collected"
    assert (
        receipt.problems[0].code == "instrument_driver_unsupported_acquisition_result"
    )


def test_acquisition_transport_loss_reports_unknown() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="s_parameter",
                    interface_id=NETWORK_SWEEP,
                    acquisition_id="sweep",
                    result_id="s_parameter",
                    unit="ratio",
                    dtype="complex128",
                )
            ],
        )
    )

    assert receipt.status == "unknown"
    assert receipt.problems[0].code == "instrument_collect_outcome_unknown"


def test_collect_contract_mismatch_is_rejected_without_trigger() -> None:
    driver = KeysightE5080B("vna", ScriptedTransport([]))
    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="s_parameter",
                    interface_id=NETWORK_SWEEP,
                    acquisition_id="sweep",
                    result_id="s_parameter",
                    unit="ratio",
                    dtype="float64",
                )
            ],
        )
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "instrument_driver_acquisition_dtype_mismatch"


def _mixed_dc_mode_command() -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id="bias",
        assignments=[
            InstrumentStateAssignment(
                resource_id="bias",
                interface_id=DC_SOURCE,
                property_id="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            ),
            InstrumentStateAssignment(
                resource_id="bias",
                interface_id=DC_SOURCE,
                property_id="current_level",
                value=StateValue(Quantity(1.0e-3, "A")),
            ),
        ],
    )
