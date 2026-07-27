from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)

from scopecat_instruments import (
    KeysightE5080B,
    LakeShore372,
    ScriptedTransport,
    TransportError,
    VirtualDcSource,
    VirtualLabWorld,
    YokogawaGS200,
)


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
            fields=[
                InstrumentStateCommandField(
                    resource_id="fridge",
                    capability_id="temperature_readout",
                    field_path="heater_range",
                    value=StateValue(1),
                )
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_read_only_field"


def test_invalid_gs200_mode_is_not_applied_without_io() -> None:
    driver = YokogawaGS200("bias", ScriptedTransport([]))
    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="bias",
            fields=[
                InstrumentStateCommandField(
                    resource_id="bias",
                    capability_id="dc_output",
                    field_path="source_mode",
                    value=StateValue(17),
                )
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "instrument_driver_field_value_mismatch"


def test_real_gs200_rejects_mixed_modes_without_io() -> None:
    transport = ScriptedTransport([])
    driver = YokogawaGS200("bias", transport)

    receipt = driver.apply_state(_mixed_dc_mode_command())

    assert receipt.status == "not_applied"
    assert receipt.problems[0].code == "gs200_conflicting_source_modes"
    assert transport.transcript == []


def test_virtual_dc_rejects_mixed_modes_without_mutation() -> None:
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
    assert receipt.problems[0].code == "virtual_dc_conflicting_source_modes"
    assert (
        after.source_mode,
        after.voltage_level_v,
        after.current_level_a,
    ) == before_values


def test_apply_transport_loss_reports_unknown_not_not_applied() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.apply_state(InstrumentStateCommand(instrument_id="vna"))

    assert receipt.status == "unknown"
    assert receipt.problems[0].code == "instrument_apply_outcome_unknown"


def test_unsupported_collect_product_is_not_collected_without_trigger() -> None:
    driver = KeysightE5080B("vna", ScriptedTransport([]))
    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="not_a_trace",
                    capability_id="network_sweep",
                )
            ],
        )
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "instrument_driver_unsupported_product"


def test_acquisition_transport_loss_reports_unknown() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="s_parameter",
                    capability_id="network_sweep",
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
                CollectProductRequest(
                    id="s_parameter",
                    capability_id="network_sweep",
                    unit="ratio",
                    dtype="float64",
                )
            ],
        )
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "instrument_driver_product_dtype_mismatch"


def _mixed_dc_mode_command() -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id="bias",
        fields=[
            InstrumentStateCommandField(
                resource_id="bias",
                capability_id="dc_output",
                field_path="voltage_level",
                value=StateValue(Quantity(0.1, "V")),
            ),
            InstrumentStateCommandField(
                resource_id="bias",
                capability_id="dc_output",
                field_path="current_level",
                value=StateValue(Quantity(1.0e-3, "A")),
            ),
        ],
    )
