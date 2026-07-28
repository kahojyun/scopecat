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
from scopecat.records.artifact import CommandPayload, command_payload_from_bytes
from scopecat.records.instrument import (
    CommandChannelBinding as RecordCommandChannelBinding,
)
from scopecat.records.instrument import (
    InstrumentPropertyState as RecordInstrumentPropertyState,
)
from scopecat.records.instrument import (
    InstrumentReadback as RecordInstrumentReadback,
)
from scopecat.records.instrument import (
    InstrumentStateSnapshot as RecordInstrumentStateSnapshot,
)
from scopecat.records.measurement import MeasurementArray, MeasurementDType
from scopecat.sdk.instruments import (
    CollectAxisRequest,
    CollectCommand,
    CollectReceipt,
    CollectResultRequest,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
    PropertySpec,
    acquisition,
    acquisition_axis,
    acquisition_result,
    apply_state_command_to_snapshot,
    bool_property,
    enum_property,
    float_property,
    int_property,
    interface,
    payload_property,
    quantity_property,
    string_property,
    validate_collect_command,
    validate_collect_receipt,
    validate_state_assignments,
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
        "InstrumentPropertyState": RecordInstrumentPropertyState,
        "InstrumentStateSnapshot": RecordInstrumentStateSnapshot,
    }

    for name, owner in owners.items():
        assert getattr(instrument_sdk, name) is owner


@pytest.mark.parametrize(
    ("property_spec", "expected"),
    [
        (bool_property("enabled"), {"id": "enabled", "value_type": {"type": "bool"}}),
        (
            int_property("averages", minimum=1, maximum=16),
            {
                "id": "averages",
                "value_type": {"type": "int", "minimum": 1, "maximum": 16},
            },
        ),
        (float_property("gain"), {"id": "gain", "value_type": {"type": "float"}}),
        (
            string_property("label"),
            {
                "id": "label",
                "value_type": {"type": "string"},
            },
        ),
        (
            enum_property("mode", choices=("standby", "operate")),
            {
                "id": "mode",
                "value_type": {
                    "type": "string",
                    "choices": ["standby", "operate"],
                },
            },
        ),
        (
            quantity_property("frequency", unit="GHz"),
            {
                "id": "frequency",
                "value_type": {"type": "quantity", "unit": "GHz"},
            },
        ),
        (
            payload_property("program", schema_id="pulse_program"),
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
def test_property_spec_has_stable_scalar_wire_format(
    property_spec: PropertySpec,
    expected: dict[str, object],
) -> None:
    compact = property_spec.model_dump(mode="json", exclude_defaults=True)
    restored = PropertySpec.model_validate(compact)
    restored_from_json = PropertySpec.model_validate_json(
        property_spec.model_dump_json()
    )

    assert compact == expected
    assert restored == property_spec
    assert restored_from_json == property_spec


def test_property_spec_wire_schema_matches_supported_state_values() -> None:
    schema = PropertySpec.model_json_schema(mode="validation")
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
def test_property_spec_rejects_unsupported_or_transient_types(
    value_type: object,
) -> None:
    with pytest.raises(ValidationError):
        PropertySpec.model_validate({"id": "value", "value_type": value_type})


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
        interface_id="test.set_frequency/v1",
        property_id="frequency",
        value=quantity_state(5.0, "GHz"),
    )

    description = instrument.describe()
    current = instrument.read_state()
    result = instrument.apply_state(command)
    updated = apply_state_command_to_snapshot(current, command)
    no_change = _changed_state_command(updated, command)

    assert description.instrument_id == "source-0"
    assert description.interfaces[0].properties[0].id == "frequency"
    assert description.interfaces[0].properties[0].value_type == Scalar(
        QuantityType(unit="GHz")
    )
    assert result.problems == ()
    assert instrument.applied[0] == command
    assert updated.properties[0].value == quantity_state(5.0, "GHz")
    with pytest.raises(ValidationError):
        updated.properties[0].value.root = 1.0
    updated_quantity = updated.properties[0].value.root
    assert isinstance(updated_quantity, Quantity)
    with pytest.raises(ValidationError):
        updated_quantity.value = 6.0
    assert no_change.assignments == []


def test_instrument_driver_validator_checks_declared_property_shapes() -> None:
    description = SignalInstrumentDriver().describe()

    unsupported = validate_state_command(
        command=_state_command(
            interface_id="test.set_frequency/v1",
            property_id="amplitude",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )
    unit_mismatch = validate_state_command(
        command=_state_command(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=quantity_state(1.0, "ns"),
        ),
        description=description,
    )
    type_mismatch = validate_state_command(
        command=_state_command(
            interface_id="test.set_gain/v1",
            property_id="gain",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )

    assert unsupported[0].code == "instrument_driver_unsupported_property"
    assert unit_mismatch[0].code == "instrument_driver_property_value_mismatch"
    assert type_mismatch[0].code == "instrument_driver_property_value_mismatch"


def test_instrument_driver_validator_rejects_writes_to_read_only_properties() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.read_only_driver",
        implementation_version="v0",
        interfaces=[
            interface(
                "test.status/v1",
                properties=[
                    quantity_property(
                        "temperature",
                        unit="K",
                        access="read_only",
                    )
                ],
            )
        ],
    )

    problems = validate_state_command(
        command=_state_command(
            interface_id="test.status/v1",
            property_id="temperature",
            value=quantity_state(0.02, "K"),
        ),
        description=description,
    )

    assert [item.code for item in problems] == ["instrument_driver_read_only_property"]


def test_instrument_driver_validator_applies_scalar_constraints() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.constraint_driver",
        implementation_version="v0",
        interfaces=[
            interface(
                "test.set_gain/v1",
                properties=[
                    PropertySpec(
                        id="gain",
                        value_type=Scalar(Float(minimum=0.0, maximum=1.0)),
                    )
                ],
            ),
            interface(
                "test.set_frequency/v1",
                properties=[
                    PropertySpec(
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
            interface_id="test.set_gain/v1",
            property_id="gain",
            value=number_state(0.5),
        ),
        description=description,
    )
    out_of_range_gain = validate_state_command(
        command=_state_command(
            interface_id="test.set_gain/v1",
            property_id="gain",
            value=number_state(2.0),
        ),
        description=description,
    )
    compatible_frequency = validate_state_command(
        command=_state_command(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=quantity_state(5_000.0, "MHz"),
        ),
        description=description,
    )
    out_of_range_frequency = validate_state_command(
        command=_state_command(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=quantity_state(7.0, "GHz"),
        ),
        description=description,
    )
    implicit_unit_frequency = validate_state_command(
        command=_state_command(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=number_state(5.0),
        ),
        description=description,
    )

    assert valid_gain == []
    assert compatible_frequency == []
    assert out_of_range_gain[0].code == "instrument_driver_property_value_mismatch"
    assert out_of_range_frequency[0].code == "instrument_driver_property_value_mismatch"
    assert implicit_unit_frequency == []


def test_instrument_driver_validator_checks_payload_references_and_schemas() -> None:
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id="pulse_program",
        codec_id="tests.canonical-json",
        codec_version=1,
        media_type="application/json",
        content=b'{"samples":[0.0]}',
    )
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.payload_driver",
        implementation_version="v0",
        interfaces=[
            interface(
                "test.play_program/v1",
                properties=[payload_property("program", schema_id="pulse_program")],
            )
        ],
    )
    wrong_schema_description = description.model_copy(
        update={
            "interfaces": [
                interface(
                    "test.play_program/v1",
                    properties=[
                        payload_property("program", schema_id="readout_program")
                    ],
                )
            ]
        }
    )
    command_with_payload = _state_command(
        interface_id="test.play_program/v1",
        property_id="program",
        value=payload_state(payload.id),
        payloads={payload.id: payload},
    )
    command_wire = command_with_payload.model_dump(mode="json")

    assert command_wire["payloads"][payload.id]["schema_id"] == "pulse_program"
    assert command_wire["payloads"][payload.id]["codec_id"] == "tests.canonical-json"
    assert command_wire["payloads"][payload.id]["body"]["kind"] == "inline"
    assert (
        InstrumentStateCommand.model_validate_json(
            command_with_payload.model_dump_json()
        )
        == command_with_payload
    )

    valid = validate_state_assignments(
        instrument_id="source-0",
        assignments=command_with_payload.assignments,
        description=description,
        payload_schemas={payload.id: payload.schema_id},
    )
    command_payload = validate_state_command(
        command=command_with_payload,
        description=description,
    )
    missing = validate_state_assignments(
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.play_program/v1",
                property_id="program",
                value=payload_state("missing-program"),
            )
        ],
        description=description,
        payload_schemas={payload.id: payload.schema_id},
    )
    not_a_reference = validate_state_command(
        command=_state_command(
            interface_id="test.play_program/v1",
            property_id="program",
            value=StateValue("program-a"),
        ),
        description=description,
    )
    wrong_schema = validate_state_assignments(
        instrument_id="source-0",
        assignments=command_with_payload.assignments,
        description=wrong_schema_description,
        payload_schemas={payload.id: payload.schema_id},
    )

    assert valid == []
    assert command_payload == []
    assert missing[0].code == "instrument_driver_unknown_payload"
    assert not_a_reference[0].code == "instrument_driver_property_value_mismatch"
    assert wrong_schema[0].code == "instrument_driver_property_value_mismatch"


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
    assert [interface.id for interface in description.instruments[0].interfaces] == [
        "test.set_frequency/v1",
        "test.scalar_signal/v1",
    ]


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


def test_provider_description_rejects_conflicting_interface_specs() -> None:
    def described(instrument_id: str, property_id: str) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=instrument_id,
            implementation_id=f"tests.{instrument_id}",
            implementation_version="v1",
            interfaces=[
                interface(
                    "test.shared_source/v1",
                    properties=[float_property(property_id)],
                )
            ],
        )

    with pytest.raises(ValueError, match="one stable specification"):
        InstrumentProviderDescription(
            provider_id="tests.conflicting-interfaces",
            instruments=(
                described("source-a", "level"),
                described("source-b", "amplitude"),
            ),
        )


def test_collect_command_rejects_duplicate_request_ids() -> None:
    request = CollectResultRequest(
        id="signal",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
    )

    with pytest.raises(ValidationError, match="request ids must be unique"):
        CollectCommand(
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[request, request],
        )


def test_instrument_description_rejects_duplicate_interface_members() -> None:
    with pytest.raises(ValidationError, match="property ids must be unique"):
        interface(
            "test.source/v1",
            properties=[float_property("level"), float_property("level")],
        )
    with pytest.raises(
        ValidationError,
        match="acquisition result ids must be unique",
    ):
        acquisition(
            "sample",
            results=[
                acquisition_result("signal"),
                acquisition_result("signal"),
            ],
        )
    duplicate_interface = interface("test.source/v1")
    with pytest.raises(
        ValidationError,
        match="instrument interface ids must be unique",
    ):
        InstrumentDescription(
            instrument_id="source-0",
            implementation_id="tests.duplicate_interfaces",
            implementation_version="v0",
            interfaces=[duplicate_interface, duplicate_interface],
        )


def test_acquisition_result_rejects_duplicate_axis_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="acquisition result axis ids must be unique",
    ):
        acquisition_result(
            "signal",
            axes=[
                acquisition_axis("frequency", kind="frequency"),
                acquisition_axis("frequency", kind="frequency"),
            ],
        )


def test_collect_validator_reports_unsupported_result_without_crashing() -> None:
    problems = validate_collect_command(
        command=CollectCommand(
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="missing",
                    interface_id="test.trace/v1",
                    acquisition_id="sample",
                    result_id="missing",
                )
            ],
        ),
        description=_collect_description(),
    )

    assert [item.code for item in problems] == [
        "instrument_driver_unsupported_acquisition_result"
    ]


def test_collect_validator_accepts_compatible_units_and_dynamic_shapes() -> None:
    compatible = validate_collect_command(
        command=_collect_command(
            unit="GHz",
            dimensions=[
                CollectAxisRequest(
                    id="frequency",
                    kind="frequency",
                    size=17,
                    unit="MHz",
                )
            ],
        ),
        description=_collect_description(),
    )
    unspecified_dynamic_shape = validate_collect_command(
        command=_collect_command(unit=None, dimensions=[]),
        description=_collect_description(),
    )

    assert compatible == []
    assert unspecified_dynamic_shape == []


def test_collect_validator_checks_dtype_unit_and_axis_contracts() -> None:
    problems = validate_collect_command(
        command=_collect_command(
            dtype="string",
            unit="K",
            dimensions=[
                CollectAxisRequest(
                    id="time",
                    kind="time",
                    size=3,
                    unit="K",
                )
            ],
        ),
        description=_collect_description(),
    )

    assert {item.code for item in problems} == {
        "instrument_driver_acquisition_dtype_mismatch",
        "instrument_driver_acquisition_unit_mismatch",
        "instrument_driver_acquisition_axis_mismatch",
        "instrument_driver_acquisition_axis_unit_mismatch",
    }


def test_collect_receipt_validator_checks_results_and_value_contract() -> None:
    command = _collect_command(
        dimensions=[
            CollectAxisRequest(
                id="frequency",
                kind="frequency",
                size=2,
                unit="Hz",
            )
        ]
    )
    valid = validate_collect_receipt(
        command=command,
        receipt=CollectReceipt(
            readback=RecordInstrumentReadback(
                values={
                    "signal": MeasurementArray(
                        dtype="float64",
                        unit="GHz",
                        shape=(2,),
                        values=(1.0, 2.0),
                    )
                }
            )
        ),
    )
    invalid = validate_collect_receipt(
        command=command,
        receipt=CollectReceipt(
            readback=RecordInstrumentReadback(
                values={
                    "unexpected": MeasurementArray(
                        dtype="string",
                        shape=(1,),
                        values=("bad",),
                    )
                }
            )
        ),
    )
    mismatched_value = validate_collect_receipt(
        command=command,
        receipt=CollectReceipt(
            readback=RecordInstrumentReadback(
                values={
                    "signal": MeasurementArray(
                        dtype="string",
                        shape=(1,),
                        values=("bad",),
                    )
                }
            )
        ),
    )

    assert valid == []
    assert {item.code for item in invalid} == {
        "instrument_driver_missing_acquisition_result",
        "instrument_driver_unexpected_acquisition_result",
    }
    assert {item.code for item in mismatched_value} == {
        "instrument_driver_readback_dtype_mismatch",
        "instrument_driver_readback_unit_mismatch",
        "instrument_driver_readback_shape_mismatch",
    }


def test_collect_receipt_validator_allows_unspecified_dynamic_shape() -> None:
    problems = validate_collect_receipt(
        command=_collect_command(dimensions=[]),
        receipt=CollectReceipt(
            readback=RecordInstrumentReadback(
                values={
                    "signal": MeasurementArray(
                        dtype="float64",
                        unit="Hz",
                        shape=(3,),
                        values=(1.0, 2.0, 3.0),
                    )
                }
            )
        ),
    )

    assert problems == []


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
    assert instrument.applied[0].assignments[0].interface_id == "test.set_frequency/v1"


def _state_command(
    *,
    interface_id: str,
    property_id: str,
    value: StateValue,
    payloads: dict[str, CommandPayload] | None = None,
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id=interface_id,
                property_id=property_id,
                value=value,
            )
        ],
        payloads=payloads or {},
    )


def _collect_description() -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.collect_driver",
        implementation_version="v0",
        interfaces=[
            interface(
                "test.trace/v1",
                acquisitions=[
                    acquisition(
                        "sample",
                        results=[
                            acquisition_result(
                                "signal",
                                dtype="float64",
                                unit="Hz",
                                axes=[
                                    acquisition_axis(
                                        "frequency",
                                        kind="frequency",
                                        unit="Hz",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _collect_command(
    *,
    dtype: MeasurementDType = "float64",
    unit: str | None = "Hz",
    dimensions: list[CollectAxisRequest],
) -> CollectCommand:
    return CollectCommand(
        instrument_id="source-0",
        point_index=0,
        point_count=1,
        requests=[
            CollectResultRequest(
                id="signal",
                interface_id="test.trace/v1",
                acquisition_id="sample",
                result_id="signal",
                dtype=dtype,
                unit=unit,
                dimensions=dimensions,
            )
        ],
    )


def _changed_state_command(
    snapshot: InstrumentStateSnapshot,
    command: InstrumentStateCommand,
) -> InstrumentStateCommand:
    current = {
        (
            property.interface_id,
            tuple(property.component_path),
            property.property_id,
        ): property.value
        for property in snapshot.properties
    }
    return InstrumentStateCommand(
        instrument_id=command.instrument_id,
        assignments=[
            assignment
            for assignment in command.assignments
            if current.get(
                (
                    assignment.interface_id,
                    tuple(assignment.component_path),
                    assignment.property_id,
                )
            )
            != assignment.value
        ],
    )
