from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.instruments import (
    CapabilityField,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    capability,
    float_field,
    payload_field,
    quantity_field,
    validate_state_command,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.execution import InstrumentStateEvidence
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.value_types import Bool, Float, Payload, Scalar
from scopecat.value_types import Quantity as QuantityType
from tests.support.execution import execute_bound_run
from tests.support.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    number_state,
    payload_state,
    quantity_state,
)
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_experiment


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        (float_field("gain"), {"id": "gain", "value_type": {"type": "float"}}),
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
    variants = schema["$defs"][definition_name]["oneOf"]

    assert [variant["properties"]["type"]["const"] for variant in variants] == [
        "float",
        "quantity",
        "payload",
    ]
    assert all(variant["additionalProperties"] is False for variant in variants)
    assert all(
        variant["properties"]["nullable"]["const"] is False for variant in variants
    )
    assert all(
        variant["properties"]["finite"]["const"] is True for variant in variants[:2]
    )
    assert variants[1]["dependentRequired"] == {
        "minimum": ["unit"],
        "maximum": ["unit"],
    }
    assert variants[-1]["required"] == ["type", "schema_id"]
    assert schema["properties"]["metadata"]["propertyNames"] == {
        "not": {"const": "payload_kinds"}
    }


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Bool()),
        Scalar(Float(), nullable=True),
        Scalar(Float(finite=False)),
        Scalar(Payload("pulse_program", python_type=dict)),
        {"type": "float", "finite": "false"},
        {"type": "payload", "schema_id": "pulse_program", "python_type": "dict"},
    ],
)
def test_capability_field_rejects_unsupported_or_transient_types(
    value_type: object,
) -> None:
    with pytest.raises(ValidationError):
        CapabilityField.model_validate({"id": "value", "value_type": value_type})


def test_capability_field_rejects_legacy_shape_and_metadata() -> None:
    with pytest.raises(ValidationError):
        CapabilityField.model_validate(
            {"id": "frequency", "kind": "quantity", "unit": "GHz"}
        )
    with pytest.raises(ValidationError, match="payload_kinds is no longer metadata"):
        CapabilityField(
            id="program",
            value_type=Scalar(Payload("pulse_program")),
            metadata={"payload_kinds": ["pulse_program"]},
        )


def test_instrument_description_rejects_legacy_schema_version() -> None:
    data = SignalInstrumentDriver().describe().model_dump(mode="json")
    data["schema_version"] = "scopecat.instrument_description.v0"

    with pytest.raises(ValidationError):
        InstrumentDescription.model_validate(data)


def test_instrument_state_models_reject_legacy_schema_versions() -> None:
    snapshot_data = InstrumentStateSnapshot(instrument_id="source-0").model_dump(
        mode="json"
    )
    snapshot_data["schema_version"] = "scopecat.instrument_state_snapshot.v0"
    with pytest.raises(ValidationError):
        InstrumentStateSnapshot.model_validate(snapshot_data)

    command_data = InstrumentStateCommand(instrument_id="source-0").model_dump(
        mode="json"
    )
    command_data["schema_version"] = "scopecat.instrument_state_command.v1"
    with pytest.raises(ValidationError):
        InstrumentStateCommand.model_validate(command_data)

    evidence_data = InstrumentStateEvidence(run_id="run-0").model_dump(mode="json")
    evidence_data["schema_version"] = "scopecat.instrument_state_evidence.v1"
    with pytest.raises(ValidationError):
        InstrumentStateEvidence.model_validate(evidence_data)


@pytest.mark.parametrize(
    ("state_value", "wire"),
    [
        (StateValue(1), 1.0),
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
    assert not hasattr(state_value, "kind")


def test_state_value_schema_exposes_three_structural_scalar_branches() -> None:
    schema = StateValue.model_json_schema(mode="validation")
    state_schema = schema["$defs"]["StateLiteral"]

    assert state_schema["anyOf"] == [
        {"type": "number"},
        {"$ref": "#/$defs/Quantity"},
        {"$ref": "#/$defs/PayloadRef"},
    ]
    assert schema["$defs"]["PayloadRef"]["required"] == ["payload_id"]
    assert schema["$defs"]["PayloadRef"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "legacy_wire",
    [
        {"kind": "number", "value": 1.0},
        {
            "kind": "quantity",
            "quantity": {"value": 5.0, "unit": "GHz"},
        },
        {"kind": "payload", "payload_id": "program-a"},
    ],
)
def test_state_value_rejects_legacy_kind_wire(legacy_wire: object) -> None:
    with pytest.raises(ValidationError):
        StateValue.model_validate(legacy_wire)


def test_concrete_state_values_reject_coercive_and_non_finite_numbers() -> None:
    invalid_values = (
        True,
        "0.5",
        Decimal("0.5"),
        Fraction(1, 2),
        float("nan"),
        float("inf"),
        10**1000,
    )
    for value in invalid_values:
        with pytest.raises(ValidationError):
            StateValue.model_validate(value)
        with pytest.raises(ValidationError):
            StateValue.model_validate({"value": value, "unit": "GHz"})
    with pytest.raises(ValidationError):
        StateValue.model_validate({"payload_id": ""})

    assert StateValue.model_validate(1).root == 1.0


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
    assert updated.fields[0].value is not command.fields[0].value
    assert updated.fields[0].value.root is not command.fields[0].value.root
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
    number_frequency = validate_state_command(
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
    assert number_frequency[0].code == "instrument_driver_field_value_mismatch"


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

    assert command_wire["schema_version"] == "scopecat.instrument_state_command.v3"
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
    assert wrong_schema[0].code == "instrument_driver_field_value_mismatch"


def test_provider_builds_fresh_drivers() -> None:
    class Provider:
        @property
        def provider_id(self) -> str:
            return "tests.driver_provider"

        def describe(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderDescription:
            assert context.config.workspace_id == "example-workspace"
            return InstrumentProviderDescription(
                provider_id=self.provider_id,
                instruments=(SignalInstrumentDriver().describe(),),
                label="Driver provider",
                metadata={"mode": "test_offline"},
            )

        def provide(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderResult:
            assert context.config.workspace_id == "example-workspace"
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


def test_execute_run_accepts_instrument_driver(tmp_path: Path) -> None:
    instrument = SignalInstrumentDriver()

    manifest, snapshot = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        workspace=tmp_path,
    )

    assert manifest.status == "completed"
    assert snapshot.instrument_ids == ["source-0"]
    assert snapshot.measurement_count == 3
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
    value,
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
