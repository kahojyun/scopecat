from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

import scopecat.sdk.instruments as instrument_sdk
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_types import Entity, Float, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import (
    CommandChannelBinding as RecordCommandChannelBinding,
)
from scopecat.records.instrument import (
    InstrumentReadback as RecordInstrumentReadback,
)
from scopecat.records.instrument import (
    InstrumentStateField as RecordInstrumentStateField,
)
from scopecat.records.instrument import (
    InstrumentStateSnapshot as RecordInstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    CapabilityField,
    CollectCommand,
    CollectProductRequest,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    bool_field,
    capability,
    enum_field,
    float_field,
    int_field,
    payload_field,
    quantity_field,
    string_field,
    validate_state_command,
)
from tests.testkit.execution import execute_bound_run
from tests.testkit.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    number_state,
    payload_state,
    quantity_state,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_experiment


def test_instrument_records_are_public_from_the_sdk_facade() -> None:
    owners = {
        "CommandChannelBinding": RecordCommandChannelBinding,
        "InstrumentReadback": RecordInstrumentReadback,
        "InstrumentStateField": RecordInstrumentStateField,
        "InstrumentStateSnapshot": RecordInstrumentStateSnapshot,
    }

    for name, owner in owners.items():
        assert getattr(instrument_sdk, name) is owner


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        (bool_field("enabled"), {"id": "enabled", "value_type": {"type": "bool"}}),
        (
            int_field("averages", minimum=1, maximum=16),
            {
                "id": "averages",
                "value_type": {"type": "int", "minimum": 1, "maximum": 16},
            },
        ),
        (float_field("gain"), {"id": "gain", "value_type": {"type": "float"}}),
        (
            string_field("label"),
            {
                "id": "label",
                "value_type": {"type": "string"},
            },
        ),
        (
            enum_field("mode", choices=("standby", "operate")),
            {
                "id": "mode",
                "value_type": {
                    "type": "string",
                    "choices": ["standby", "operate"],
                },
            },
        ),
        (
            quantity_field("frequency", unit="GHz"),
            {
                "id": "frequency",
                "value_type": {"type": "quantity", "unit": "GHz"},
            },
        ),
        (
            payload_field("program", schema_id="pulse_program"),
            {
                "id": "program",
                "value_type": {
                    "type": "payload",
                    "schema_id": "pulse_program",
                },
            },
        ),
    ],
)
def test_capability_field_has_stable_scalar_wire_format(
    field: CapabilityField,
    expected: dict[str, object],
) -> None:
    compact = field.model_dump(mode="json", exclude_defaults=True)
    restored = CapabilityField.model_validate(compact)
    restored_from_json = CapabilityField.model_validate_json(field.model_dump_json())

    assert compact == expected
    assert restored == field
    assert restored_from_json == field


def test_capability_field_wire_schema_matches_supported_state_values() -> None:
    schema = CapabilityField.model_json_schema(mode="validation")
    value_schema = schema["properties"]["value_type"]
    definition_name = value_schema["$ref"].rsplit("/", maxsplit=1)[-1]
    alias = schema["$defs"][definition_name]
    wire = schema["$defs"][alias["$ref"].rsplit("/", maxsplit=1)[-1]]
    variants = [
        schema["$defs"][variant["$ref"].rsplit("/", maxsplit=1)[-1]]
        for variant in wire["oneOf"]
    ]

    assert [variant["properties"]["type"]["const"] for variant in variants] == [
        "bool",
        "int",
        "float",
        "string",
        "quantity",
        "payload",
    ]
    assert all(variant["additionalProperties"] is False for variant in variants)
    assert variants[2]["properties"]["finite"]["const"] is True
    assert variants[4]["properties"]["finite"]["const"] is True
    assert variants[-1]["required"] == ["type", "schema_id"]


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Entity()),
        Scalar(Float(finite=False)),
        {"type": "float", "finite": "false"},
        {"type": "quantity", "minimum": 1.0},
    ],
)
def test_capability_field_rejects_unsupported_or_transient_types(
    value_type: object,
) -> None:
    with pytest.raises(ValidationError):
        CapabilityField.model_validate({"id": "value", "value_type": value_type})


@pytest.mark.parametrize(
    ("state_value", "wire"),
    [
        (StateValue(True), True),
        (StateValue(1), 1),
        (StateValue(1.0), 1.0),
        (StateValue("operate"), "operate"),
        (
            StateValue(Quantity(value=5.0, unit="GHz")),
            {"value": 5.0, "unit": "GHz"},
        ),
        (
            StateValue(PayloadRef(payload_id="program-a")),
            {"payload_id": "program-a"},
        ),
    ],
)
def test_state_value_has_stable_structural_wire_format(
    state_value: StateValue,
    wire: object,
) -> None:
    assert state_value.model_dump(mode="json") == wire
    assert StateValue.model_validate(wire) == state_value
    assert StateValue.model_validate_json(state_value.model_dump_json()) == state_value


def test_state_value_schema_exposes_six_structural_scalar_branches() -> None:
    schema = StateValue.model_json_schema(mode="validation")
    state_schema = schema["$defs"]["StateLiteral"]

    assert state_schema["anyOf"] == [
        {"type": "boolean"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "string"},
        {"$ref": "#/$defs/Quantity"},
        {"$ref": "#/$defs/PayloadRef"},
    ]
    assert schema["$defs"]["PayloadRef"]["required"] == ["payload_id"]
    assert schema["$defs"]["PayloadRef"]["additionalProperties"] is False


def test_concrete_state_values_reject_coercive_and_non_finite_numbers() -> None:
    for value in (Decimal("0.5"), Fraction(1, 2)):
        with pytest.raises(ValidationError):
            StateValue.model_validate(value)
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            StateValue.model_validate(value)
        with pytest.raises(ValidationError):
            StateValue.model_validate({"value": value, "unit": "GHz"})
    for value in (True, "0.5", Decimal("0.5"), Fraction(1, 2)):
        with pytest.raises(ValidationError):
            StateValue.model_validate({"value": value, "unit": "GHz"})
    with pytest.raises(ValidationError):
        StateValue.model_validate({"payload_id": ""})

    assert StateValue.model_validate(True).root is True
    assert StateValue.model_validate(1).root == 1
    assert StateValue.model_validate("0.5").root == "0.5"


def test_instrument_driver_generates_description_and_applies_state() -> None:
    instrument = SignalInstrumentDriver()
    command = _state_command(
        capability_id="set_frequency",
        field_path="frequency",
        value=quantity_state(5.0, "GHz"),
    )

    description = instrument.describe()
    current = instrument.read_state()
    result = instrument.apply_state(command)
    updated = apply_state_command_to_snapshot(current, command)
    no_change = _changed_state_command(updated, command)

    assert description.instrument_id == "source-0"
    assert description.capabilities[0].fields[0].id == "frequency"
    assert description.capabilities[0].fields[0].value_type == Scalar(
        QuantityType(unit="GHz")
    )
    assert result.problems == ()
    assert instrument.applied[0] == command
    assert updated.fields[0].value == quantity_state(5.0, "GHz")
    with pytest.raises(ValidationError):
        updated.fields[0].value.root = 1.0
    updated_quantity = updated.fields[0].value.root
    assert isinstance(updated_quantity, Quantity)
    with pytest.raises(ValidationError):
        updated_quantity.value = 6.0
    assert no_change.fields == []


def test_instrument_driver_validator_checks_declared_field_shapes() -> None:
    description = SignalInstrumentDriver().describe()

    unsupported = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="amplitude",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )
    unit_mismatch = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(1.0, "ns"),
        ),
        description=description,
    )
    type_mismatch = validate_state_command(
        command=_state_command(
            capability_id="set_gain",
            field_path="gain",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )

    assert unsupported[0].code == "instrument_driver_unsupported_field"
    assert unit_mismatch[0].code == "instrument_driver_field_value_mismatch"
    assert type_mismatch[0].code == "instrument_driver_field_value_mismatch"


def test_instrument_driver_validator_applies_scalar_constraints() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.constraint_driver",
        implementation_version="v0",
        capabilities=[
            capability(
                "set_gain",
                fields=[
                    CapabilityField(
                        id="gain",
                        value_type=Scalar(Float(minimum=0.0, maximum=1.0)),
                    )
                ],
            ),
            capability(
                "set_frequency",
                fields=[
                    CapabilityField(
                        id="frequency",
                        value_type=Scalar(
                            QuantityType(unit="GHz", minimum=4.0, maximum=6.0)
                        ),
                    )
                ],
            ),
        ],
    )

    valid_gain = validate_state_command(
        command=_state_command(
            capability_id="set_gain",
            field_path="gain",
            value=number_state(0.5),
        ),
        description=description,
    )
    out_of_range_gain = validate_state_command(
        command=_state_command(
            capability_id="set_gain",
            field_path="gain",
            value=number_state(2.0),
        ),
        description=description,
    )
    compatible_frequency = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(5_000.0, "MHz"),
        ),
        description=description,
    )
    out_of_range_frequency = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(7.0, "GHz"),
        ),
        description=description,
    )
    implicit_unit_frequency = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="frequency",
            value=number_state(5.0),
        ),
        description=description,
    )

    assert valid_gain == []
    assert compatible_frequency == []
    assert out_of_range_gain[0].code == "instrument_driver_field_value_mismatch"
    assert out_of_range_frequency[0].code == "instrument_driver_field_value_mismatch"
    assert implicit_unit_frequency == []


def test_instrument_driver_validator_checks_payload_references_and_schemas() -> None:
    payload = CommandPayload(
        id="program-a",
        schema_id="pulse_program",
        payload={"samples": [0.0]},
    )
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.payload_driver",
        implementation_version="v0",
        capabilities=[
            capability(
                "play_program",
                fields=[payload_field("program", schema_id="pulse_program")],
            )
        ],
    )
    wrong_schema_description = description.model_copy(
        update={
            "capabilities": [
                capability(
                    "play_program",
                    fields=[payload_field("program", schema_id="readout_program")],
                )
            ]
        }
    )
    command_with_payload = _state_command(
        capability_id="play_program",
        field_path="program",
        value=payload_state(payload.id),
        payloads={payload.id: payload},
    )
    durable_payload = CommandPayload(
        id=payload.id,
        schema_id=payload.schema_id,
        content_hash="sha256:test-program",
    )
    durable_command = command_with_payload.model_copy(
        update={"payloads": {durable_payload.id: durable_payload}}
    )
    command_wire = durable_command.model_dump(mode="json")

    assert command_wire["payloads"][payload.id]["schema_id"] == "pulse_program"
    assert "kind" not in command_wire["payloads"][payload.id]
    assert (
        InstrumentStateCommand.model_validate_json(durable_command.model_dump_json())
        == durable_command
    )

    valid = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state(payload.id),
        ),
        description=description,
        payloads={payload.id: payload},
    )
    command_payload = validate_state_command(
        command=command_with_payload,
        description=description,
    )
    missing = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state("missing-program"),
        ),
        description=description,
        payloads={payload.id: payload},
    )
    not_a_reference = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=StateValue("program-a"),
        ),
        description=description,
        payloads={payload.id: payload},
    )
    wrong_schema = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state(payload.id),
        ),
        description=wrong_schema_description,
        payloads={payload.id: payload},
    )

    assert valid == []
    assert command_payload == []
    assert missing[0].code == "instrument_driver_unknown_payload"
    assert not_a_reference[0].code == "instrument_driver_field_value_mismatch"
    assert wrong_schema[0].code == "instrument_driver_field_value_mismatch"


def test_provider_builds_fresh_drivers() -> None:
    class Provider:
        @property
        def provider_id(self) -> str:
            return "tests.driver_provider"

        def describe(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderDescription:
            assert context.config.id == "simple-scan-profile"
            return InstrumentProviderDescription(
                provider_id=self.provider_id,
                instruments=(SignalInstrumentDriver().describe(),),
            )

        def provide(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderResult:
            assert context.config.id == "simple-scan-profile"
            return InstrumentProviderResult(drivers=(SignalInstrumentDriver(),))

    provider = Provider()
    context = InstrumentProviderContext(config=load_config())
    first = provider.provide(context)
    second = provider.provide(context)

    description = provider.describe(context)
    assert description.provider_id == "tests.driver_provider"
    assert [item.instrument_id for item in description.instruments] == ["source-0"]
    assert first.problems == ()
    assert first.drivers[0] is not second.drivers[0]


def test_provider_description_resolves_instruments_from_config() -> None:
    context = InstrumentProviderContext(config=load_config())

    description = TestSignalInstrumentProvider().describe(context)

    assert description.problems == ()
    assert [instrument.instrument_id for instrument in description.instruments] == [
        "source-0"
    ]
    assert [
        capability.id for capability in description.instruments[0].capabilities
    ] == ["set_frequency", "scalar_signal"]


def test_provider_description_reports_dynamic_selection_errors() -> None:
    context = InstrumentProviderContext(config=load_config())

    description = TestSignalInstrumentProvider(instrument_id="missing-source").describe(
        context
    )

    assert description.instruments == ()
    assert [problem.code for problem in description.problems] == [
        "test_signal_provider_unknown_instrument"
    ]


def test_provider_description_rejects_duplicate_instrument_ids() -> None:
    instrument = SignalInstrumentDriver().describe()

    with pytest.raises(ValueError, match="unique instrument ids: source-0"):
        InstrumentProviderDescription(
            provider_id="tests.duplicate-provider",
            instruments=(instrument, instrument),
        )


def test_collect_command_rejects_duplicate_request_ids() -> None:
    request = CollectProductRequest(
        id="signal",
        capability_id="scalar_signal",
    )

    with pytest.raises(ValidationError, match="request ids must be unique"):
        CollectCommand(
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[request, request],
        )


def test_run_accepts_instrument_driver(tmp_path: Path) -> None:
    instrument = SignalInstrumentDriver()

    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert len(instrument.collect_commands) == 3
    assert instrument.collect_commands[0].point_index == 0
    assert instrument.collect_commands[0].point_count == 3
    assert [request.id for request in instrument.collect_commands[0].requests] == [
        "signal"
    ]
    assert instrument.applied[0].fields[0].capability_id == "set_frequency"


def _state_command(
    *,
    capability_id: str,
    field_path: str,
    value: StateValue,
    payloads: dict[str, CommandPayload] | None = None,
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id="source-0",
        fields=[
            InstrumentStateCommandField(
                resource_id="source-0",
                capability_id=capability_id,
                field_path=field_path,
                value=value,
            )
        ],
        payloads=payloads or {},
    )


def _changed_state_command(
    snapshot: InstrumentStateSnapshot,
    command: InstrumentStateCommand,
) -> InstrumentStateCommand:
    current = {
        (field.capability_id, field.field_path): field.value
        for field in snapshot.fields
    }
    return InstrumentStateCommand(
        instrument_id=command.instrument_id,
        fields=[
            field
            for field in command.fields
            if current.get((field.capability_id, field.field_path)) != field.value
        ],
    )
