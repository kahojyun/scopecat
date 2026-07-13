from __future__ import annotations

import pytest

from scopecat.instruments import (
    CapabilityField,
    CollectCommand,
    CollectProductRequest,
    InstrumentActionCommand,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    SimpleInstrumentDriver,
    SimpleProduct,
    SimpleStateField,
    bool_field,
    enum_field,
    int_field,
    payload_field,
    product,
    simple_capability,
)
from scopecat.models.parameter import Quantity
from scopecat.models.state import StateLiteral, StateValue


def test_simple_state_only_driver_applies_typed_fields_and_defaults_lifecycle() -> None:
    device: dict[str, StateLiteral] = {
        "enabled": False,
        "averages": 1,
        "mode": "standby",
    }

    def field(name: str, description: CapabilityField) -> SimpleStateField:
        return SimpleStateField(
            field=description,
            read=lambda: device[name],
            write=lambda value: device.__setitem__(name, value),
        )

    driver = SimpleInstrumentDriver(
        instrument_id="switch-0",
        implementation_id="tests.simple-switch",
        implementation_version="1",
        capabilities=(
            simple_capability(
                "configure",
                fields=(
                    field("enabled", bool_field("enabled")),
                    field("averages", int_field("averages", minimum=1, maximum=8)),
                    field(
                        "mode",
                        enum_field("mode", choices=("standby", "operate")),
                    ),
                ),
            ),
        ),
    )

    assert [item.value.root for item in driver.read_state().fields] == [
        False,
        1,
        "standby",
    ]
    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="switch-0",
            fields=[
                _command_field("enabled", True),
                _command_field("averages", 4),
                _command_field("mode", "operate"),
            ],
        )
    )

    assert receipt.status == "applied"
    assert device == {"enabled": True, "averages": 4, "mode": "operate"}
    assert (
        driver.collect(
            CollectCommand(
                instrument_id="switch-0",
                point_index=0,
                point_count=1,
            )
        ).readback
        is not None
    )
    driver.cleanup()
    driver.abort()

    action = driver.action(
        InstrumentActionCommand(
            operation_id="reset-0",
            instrument_id="switch-0",
            capability_id="reset",
        )
    )
    assert action.status == "not_performed"
    assert action.problems[0].code == "simple_instrument_action_unsupported"


def test_simple_state_driver_rejects_all_invalid_fields_before_effects() -> None:
    writes: list[StateLiteral] = []
    driver = SimpleInstrumentDriver(
        instrument_id="switch-0",
        implementation_id="tests.simple-switch",
        implementation_version="1",
        capabilities=(
            simple_capability(
                "configure",
                fields=(
                    SimpleStateField(
                        field=enum_field("mode", choices=("standby", "operate")),
                        read=lambda: "standby",
                        write=writes.append,
                    ),
                ),
            ),
        ),
    )

    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="switch-0",
            fields=[
                _command_field("mode", "invalid"),
                _command_field("missing", "value"),
            ],
        )
    )

    assert receipt.status == "not_applied"
    assert [problem.code for problem in receipt.problems] == [
        "instrument_driver_field_value_mismatch",
        "instrument_driver_unsupported_field",
    ]
    assert writes == []


def test_simple_read_only_driver_collects_without_state_boilerplate() -> None:
    reads = 0

    def read_voltage() -> Quantity:
        nonlocal reads
        reads += 1
        return Quantity(value=0.025, unit="V")

    driver = SimpleInstrumentDriver(
        instrument_id="voltmeter-0",
        implementation_id="tests.simple-voltmeter",
        implementation_version="1",
        capabilities=(
            simple_capability(
                "voltage",
                products=(
                    SimpleProduct(
                        product=product("voltage", unit="V"),
                        read=read_voltage,
                    ),
                ),
            ),
        ),
    )

    assert driver.read_state().fields == []
    assert (
        driver.apply_state(InstrumentStateCommand(instrument_id="voltmeter-0")).status
        == "applied"
    )
    receipt = driver.collect(
        CollectCommand(
            instrument_id="voltmeter-0",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="voltage",
                    capability_id="voltage",
                    unit="V",
                )
            ],
        )
    )

    assert receipt.status == "collected"
    assert receipt.readback is not None
    assert receipt.readback.values == {"voltage": Quantity(value=0.025, unit="V")}
    assert reads == 1

    unsupported = driver.collect(
        CollectCommand(
            instrument_id="voltmeter-0",
            point_index=0,
            point_count=1,
            requests=[CollectProductRequest(id="humidity")],
        )
    )
    assert unsupported.status == "not_collected"
    assert unsupported.problems[0].code == "simple_instrument_product_unsupported"
    assert reads == 1


def test_simple_driver_rejects_payload_and_duplicate_declarations() -> None:
    with pytest.raises(ValueError, match="do not support payloads"):
        SimpleStateField(
            field=payload_field("program", schema_id="pulse_program"),
            read=lambda: StateValue(0.0),
            write=lambda _value: None,
        )

    state = SimpleStateField(
        field=bool_field("enabled"),
        read=lambda: False,
        write=lambda _value: None,
    )
    with pytest.raises(ValueError, match=r"state fields .* must be unique"):
        simple_capability("configure", fields=(state, state))


def _command_field(field_path: str, value: StateLiteral) -> InstrumentStateCommandField:
    return InstrumentStateCommandField(
        resource_id="switch-0",
        capability_id="configure",
        field_path=field_path,
        value=StateValue(value),
    )
