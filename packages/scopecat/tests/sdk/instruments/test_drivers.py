from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

import scopecat.sdk.instruments as instrument_sdk
from scopecat.kernel.problems import ModelLocation, Problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_types import Entity, Float, Int, Payload, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.planning.provider_validation import instrument_contract_fingerprint
from scopecat.records.artifact import command_payload_from_bytes
from scopecat.records.config import instrument_bindings
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
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDType,
    MeasurementUnavailable,
)
from scopecat.sdk.instruments import (
    AcquisitionCaseSpec,
    AcquisitionPreconditionSpec,
    CollectReceipt,
    DiscriminatedState,
    DriverSuccess,
    FixedAcquisitionSpec,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentStateSnapshot,
    InterfaceRef,
    OperationArgumentSpec,
    PropertyRef,
    PropertySpec,
    StateCase,
    StateDiscriminatedAcquisitionSpec,
    StatePropertyRef,
    acquisition,
    acquisition_axis,
    acquisition_case,
    acquisition_precondition,
    acquisition_result,
    acquisition_results,
    bool_property,
    component,
    discriminated_state,
    enum_property,
    float_property,
    int_property,
    interface,
    operation,
    operation_argument,
    quantity_property,
    state_case,
    state_discriminated_acquisition,
    string_property,
)
from scopecat.sdk.instruments._driver_adapter import (
    lower_state_patch,
    project_state,
)
from scopecat.sdk.instruments._projection import ProjectedInstrumentState
from scopecat.sdk.instruments.backend import lower_backend_apply_request
from scopecat.sdk.instruments.contracts import (
    CollectAxisRequest,
    CollectCommand,
    CollectResultRequest,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InteractiveCollectIntent,
    InvokeCommand,
    RejectedInteractiveCollect,
    ResolvedInteractiveCollect,
    evaluate_acquisition_readiness,
    project_instrument_state,
    resolve_acquisition_dimensions,
    resolve_interactive_collect,
    validate_collect_command,
    validate_collect_plan,
    validate_collect_receipt,
    validate_instrument_description_collection,
    validate_invoke_command,
    validate_state_command,
    validate_state_snapshot,
)
from tests.testkit.execution import execute_bound_run
from tests.testkit.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    number_state,
    quantity_state,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_experiment


def test_instrument_records_are_public_from_the_sdk_facade() -> None:
    owners = {
        "AcquisitionCaseSpec": AcquisitionCaseSpec,
        "AcquisitionPreconditionSpec": AcquisitionPreconditionSpec,
        "CommandChannelBinding": RecordCommandChannelBinding,
        "DiscriminatedState": DiscriminatedState,
        "FixedAcquisitionSpec": FixedAcquisitionSpec,
        "InstrumentReadback": RecordInstrumentReadback,
        "InstrumentPropertyState": RecordInstrumentPropertyState,
        "InstrumentStateSnapshot": RecordInstrumentStateSnapshot,
        "StateCase": StateCase,
        "StateDiscriminatedAcquisitionSpec": StateDiscriminatedAcquisitionSpec,
        "StatePropertyRef": StatePropertyRef,
    }

    for name, owner in owners.items():
        assert getattr(instrument_sdk, name) is owner

    for name in (
        "AcquisitionReadiness",
        "CollectCommand",
        "InteractiveCollectIntent",
        "ResolvedInteractiveCollect",
        "validate_collect_plan",
    ):
        assert not hasattr(instrument_sdk, name)


@pytest.mark.parametrize("dtype", ["bool", "string"])
def test_bool_and_string_acquisition_contracts_reject_units(
    dtype: MeasurementDType,
) -> None:
    with pytest.raises(ValidationError, match="cannot have a unit"):
        acquisition_result("invalid", dtype=dtype, unit="ratio")
    with pytest.raises(ValidationError, match="cannot have a unit"):
        CollectResultRequest(
            id="invalid",
            interface_id="test.readout/v1",
            acquisition_id="sample",
            result_id="invalid",
            dtype=dtype,
            unit="ratio",
        )


def test_projected_state_stays_internal_to_instrument_preflight() -> None:
    assert not hasattr(instrument_sdk, "ProjectedInstrumentState")
    assert not hasattr(instrument_sdk, "project_instrument_state")


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
            quantity_property(
                "delay",
                unit="s",
                minimum=0.0,
                maximum=999.999,
            ),
            {
                "id": "delay",
                "value_type": {
                    "type": "quantity",
                    "unit": "s",
                    "minimum": 0.0,
                    "maximum": 999.999,
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
    ]
    assert all(variant["additionalProperties"] is False for variant in variants)
    assert variants[2]["properties"]["finite"]["const"] is True
    assert variants[4]["properties"]["finite"]["const"] is True


def test_operation_argument_spec_supports_opaque_payloads() -> None:
    argument = OperationArgumentSpec(
        id="program",
        value_type=Scalar(Payload(schema_id="pulse_program")),
    )

    assert argument.model_dump(mode="json", exclude_defaults=True) == {
        "id": "program",
        "value_type": {
            "type": "payload",
            "schema_id": "pulse_program",
        },
    }


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Entity()),
        Scalar(Payload(schema_id="pulse_program")),
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
    current = project_state(instrument.instrument_id, instrument.read_state())
    request = lower_backend_apply_request(command)
    patch = lower_state_patch(request)
    result = instrument.apply_state(patch)
    updated = project_instrument_state(
        current,
        command,
        description=description,
    )

    assert description.instrument_id == "source-0"
    assert description.interfaces[0].properties[0].id == "frequency"
    assert description.interfaces[0].properties[0].value_type == Scalar(
        QuantityType(unit="GHz")
    )
    assert isinstance(result, DriverSuccess)
    assert instrument.applied[0] == patch
    assert updated.properties[0].value == quantity_state(5.0, "GHz")
    with pytest.raises(ValidationError):
        updated.properties[0].value.root = 1.0
    updated_quantity = updated.properties[0].value.root
    assert isinstance(updated_quantity, Quantity)
    with pytest.raises(ValidationError):
        updated_quantity.value = 6.0


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


def test_instrument_driver_validator_allows_write_only_commands() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.write_only_driver",
        implementation_version="v0",
        interfaces=[
            interface(
                "test.secret/v1",
                properties=[
                    string_property(
                        "token",
                        access="write_only",
                    )
                ],
            )
        ],
    )

    problems = validate_state_command(
        command=_state_command(
            interface_id="test.secret/v1",
            property_id="token",
            value=StateValue("configured"),
        ),
        description=description,
    )

    assert problems == []


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
    assert isinstance(out_of_range_gain[0].location, ModelLocation)
    assert out_of_range_gain[0].location.path == ("assignments", 0, "value")
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
                operations=[
                    operation(
                        "play",
                        arguments=[
                            operation_argument(
                                "program",
                                value_type=Scalar(Payload(schema_id="pulse_program")),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    wrong_schema_description = description.model_copy(
        update={
            "interfaces": [
                interface(
                    "test.play_program/v1",
                    operations=[
                        operation(
                            "play",
                            arguments=[
                                operation_argument(
                                    "program",
                                    value_type=Scalar(
                                        Payload(schema_id="readout_program")
                                    ),
                                )
                            ],
                        )
                    ],
                )
            ]
        }
    )
    command_with_payload = InvokeCommand(
        command_id="invoke-program",
        instrument_id="source-0",
        resource_id="source-0",
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=[
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
        ],
        payloads={payload.id: payload},
    )
    command_wire = command_with_payload.model_dump(mode="json")

    assert command_wire["payloads"][payload.id]["schema_id"] == "pulse_program"
    assert command_wire["payloads"][payload.id]["codec_id"] == "tests.canonical-json"
    assert command_wire["payloads"][payload.id]["body"]["kind"] == "inline"
    assert (
        InvokeCommand.model_validate_json(command_with_payload.model_dump_json())
        == command_with_payload
    )

    valid = validate_invoke_command(
        command=command_with_payload,
        description=description,
    )
    with pytest.raises(ValidationError, match="missing referenced payload"):
        InvokeCommand(
            command_id="missing-payload",
            instrument_id="source-0",
            resource_id="source-0",
            interface_id="test.play_program/v1",
            operation_id="play",
            arguments=[
                InstrumentOperationArgument(
                    id="program",
                    value=StateValue(PayloadRef(payload_id="missing-program")),
                )
            ],
            payloads={payload.id: payload},
        )
    not_a_reference = validate_invoke_command(
        command=InvokeCommand(
            command_id="non-reference-payload",
            instrument_id="source-0",
            resource_id="source-0",
            interface_id="test.play_program/v1",
            operation_id="play",
            arguments=[
                InstrumentOperationArgument(
                    id="program",
                    value=StateValue("program-a"),
                )
            ],
        ),
        description=description,
    )
    wrong_schema = validate_invoke_command(
        command=command_with_payload,
        description=wrong_schema_description,
    )

    assert valid == []
    assert (
        not_a_reference[0].code == "instrument_driver_operation_argument_value_mismatch"
    )
    assert wrong_schema[0].code == "instrument_driver_operation_argument_value_mismatch"


def test_provider_builds_fresh_drivers() -> None:
    class Provider:
        @property
        def provider_id(self) -> str:
            return "tests.driver_provider"

        def describe(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderDescription:
            assert [binding.id for binding in context.bindings] == ["source-0"]
            return InstrumentProviderDescription(
                provider_id=self.provider_id,
                instruments=(SignalInstrumentDriver().describe(),),
            )

        def connect(
            self, context: InstrumentConnectionContext
        ) -> SignalInstrumentDriver:
            assert context.binding.id == "source-0"
            return SignalInstrumentDriver()

    provider = Provider()
    context = InstrumentProviderContext(bindings=instrument_bindings(load_config()))
    connection = InstrumentConnectionContext(
        binding=context.bindings[0],
    )
    first = provider.connect(connection)
    second = provider.connect(connection)

    description = provider.describe(context)
    assert description.provider_id == "tests.driver_provider"
    assert [item.instrument_id for item in description.instruments] == ["source-0"]
    assert first is not second


def test_provider_description_resolves_instruments_from_config() -> None:
    context = InstrumentProviderContext(bindings=instrument_bindings(load_config()))

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
    context = InstrumentProviderContext(bindings=instrument_bindings(load_config()))

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
            command_id="duplicate-results",
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[request, request],
        )


def test_state_command_requires_one_assignment() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        InstrumentStateCommand(
            command_id="empty-apply",
            instrument_id="source-0",
            assignments=[],
        )


def test_collect_command_requires_one_acquisition() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        CollectCommand(
            command_id="empty-collect",
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[],
        )

    with pytest.raises(ValidationError, match="exactly one acquisition"):
        CollectCommand(
            command_id="mixed-acquisitions",
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="first",
                    interface_id="test.scalar_signal/v1",
                    acquisition_id="sample",
                    result_id="signal",
                ),
                CollectResultRequest(
                    id="second",
                    interface_id="test.scalar_signal/v1",
                    acquisition_id="alternate",
                    result_id="signal",
                ),
            ],
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


def test_acquisition_schema_uses_an_explicit_discriminated_union() -> None:
    fixed = acquisition(
        "sample",
        results=[acquisition_result("signal")],
    )
    description = _state_discriminated_collect_description()
    restored = InstrumentDescription.model_validate(description.model_dump(mode="json"))
    state_discriminated = restored.interfaces[1].acquisitions[0]

    assert isinstance(fixed, FixedAcquisitionSpec)
    assert fixed.model_dump(mode="json")["kind"] == "fixed"
    assert [result.id for result in acquisition_results(fixed)] == ["signal"]
    assert isinstance(state_discriminated, StateDiscriminatedAcquisitionSpec)
    assert state_discriminated.kind == "state_discriminated"
    assert isinstance(state_discriminated.discriminator, StatePropertyRef)
    assert all(
        isinstance(case, AcquisitionCaseSpec) for case in state_discriminated.cases
    )
    assert [result.id for result in acquisition_results(state_discriminated)] == [
        "monitored_current",
        "monitored_voltage",
    ]


def test_acquisition_schema_rejects_a_missing_discriminator_tag() -> None:
    description = _collect_description()
    serialized = description.model_dump(mode="json")
    del serialized["interfaces"][0]["acquisitions"][0]["kind"]

    with pytest.raises(ValidationError, match="Unable to extract tag"):
        InstrumentDescription.model_validate(serialized)


def test_state_discriminated_acquisition_requires_unique_result_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="state-discriminated acquisition result ids must be unique",
    ):
        state_discriminated_acquisition(
            "monitor",
            discriminator=InterfaceRef("test.source/v1")
            .component("output")
            .property("mode"),
            cases=(
                acquisition_case(
                    "voltage",
                    results=(acquisition_result("reading"),),
                ),
                acquisition_case(
                    "current",
                    results=(acquisition_result("reading"),),
                ),
            ),
        )


def test_acquisition_discriminator_must_reference_declared_physical_state() -> None:
    with pytest.raises(
        ValidationError,
        match="discriminator must reference a declared discriminated state",
    ):
        _state_discriminated_collect_description(
            discriminator=InterfaceRef("test.source/v1")
            .component("output")
            .property("missing")
        )


def test_acquisition_cases_must_match_discriminator_state_cases() -> None:
    with pytest.raises(
        ValidationError,
        match="case values must exactly match",
    ):
        _state_discriminated_collect_description(
            cases=(
                acquisition_case(
                    "voltage",
                    results=(acquisition_result("monitored_current", unit="A"),),
                ),
                acquisition_case(
                    "power",
                    results=(acquisition_result("monitored_power", unit="W"),),
                ),
            )
        )


def test_acquisition_readiness_uses_public_state_preconditions() -> None:
    output_enabled = (
        InterfaceRef("test.source/v1").component("output").property("output_enabled")
    )
    description = _state_discriminated_collect_description(
        preconditions=(
            acquisition_precondition(
                output_enabled,
                value=True,
                unavailable_reason="Source output is disabled.",
            ),
        )
    )
    acquisition_spec = description.interfaces[1].acquisitions[0]

    unknown = evaluate_acquisition_readiness(
        description=description,
        acquisition=acquisition_spec,
        state=None,
    )
    blocked = evaluate_acquisition_readiness(
        description=description,
        acquisition=acquisition_spec,
        state=_state_discriminated_collect_snapshot("voltage"),
    )
    ready = evaluate_acquisition_readiness(
        description=description,
        acquisition=acquisition_spec,
        state=_state_discriminated_collect_snapshot(
            "voltage",
            output_enabled=True,
        ),
    )

    assert unknown.status == "unknown"
    assert unknown.results == ()
    assert blocked.status == "blocked"
    assert blocked.active_case == "voltage"
    assert [result.id for result in blocked.results] == ["monitored_current"]
    assert [issue.reason for issue in blocked.issues] == ["Source output is disabled."]
    assert ready.status == "ready"
    assert ready.issues == ()


def test_collect_plan_checks_preconditions_but_structural_validation_does_not() -> None:
    description = _state_discriminated_collect_description(
        preconditions=(
            acquisition_precondition(
                InterfaceRef("test.source/v1")
                .component("output")
                .property("output_enabled"),
                value=True,
                unavailable_reason="Source output is disabled.",
            ),
        )
    )
    command = _state_discriminated_collect_command(
        "monitored_current",
        unit="A",
    )

    structural = validate_collect_command(
        command=command,
        description=description,
    )
    planned = validate_collect_plan(
        command=command,
        description=description,
        baseline=_state_discriminated_collect_snapshot("voltage"),
    )

    assert structural == []
    assert [problem.code for problem in planned] == [
        "instrument_driver_acquisition_precondition_not_met"
    ]
    [problem] = planned
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.root == "instrument_collect_command"
    assert isinstance(problem.related_locations[0], ModelLocation)
    assert problem.related_locations[0].root == "instrument_state"
    assert problem.related_locations[0].path == (
        "test.source/v1",
        "output",
        "output_enabled",
    )
    assert problem.details["observed_value"] is False


def test_known_common_precondition_blocks_with_an_unknown_result_case() -> None:
    description = _state_discriminated_collect_description(
        preconditions=(
            acquisition_precondition(
                InterfaceRef("test.source/v1")
                .component("output")
                .property("output_enabled"),
                value=True,
                unavailable_reason="Source output is disabled.",
            ),
        )
    )
    partial = ProjectedInstrumentState(
        instrument_id="source-0",
        properties=(
            RecordInstrumentPropertyState(
                interface_id="test.source/v1",
                component_path=["output"],
                property_id="output_enabled",
                value=StateValue(False),
            ),
        ),
    )

    planned = validate_collect_plan(
        command=_state_discriminated_collect_command(
            "monitored_current",
            unit="A",
        ),
        description=description,
        baseline=partial,
    )

    assert [problem.code for problem in planned] == [
        "instrument_driver_acquisition_precondition_not_met"
    ]


def test_acquisition_preconditions_validate_type_and_state_visibility() -> None:
    voltage_level = (
        InterfaceRef("test.source/v1").component("output").property("voltage_level")
    )

    with pytest.raises(
        ValidationError,
        match="state that is not always observable",
    ):
        _state_discriminated_collect_description(
            preconditions=(
                acquisition_precondition(
                    voltage_level,
                    value=0.1,
                    unavailable_reason="Voltage level is not configured.",
                ),
            )
        )

    description = _state_discriminated_collect_description(
        cases=(
            acquisition_case(
                "voltage",
                results=(acquisition_result("monitored_current", unit="A"),),
                preconditions=(
                    acquisition_precondition(
                        voltage_level,
                        value=0.1,
                        unavailable_reason="Voltage level is not configured.",
                    ),
                ),
            ),
            acquisition_case(
                "current",
                results=(acquisition_result("monitored_voltage", unit="V"),),
            ),
        )
    )
    acquisition_spec = description.interfaces[1].acquisitions[0]
    assert isinstance(acquisition_spec, StateDiscriminatedAcquisitionSpec)
    assert acquisition_spec.cases[0].preconditions


def test_quantity_preconditions_require_a_canonical_property_unit() -> None:
    source = InterfaceRef("test.source/v1")
    level = source.property("level")

    with pytest.raises(
        ValidationError,
        match="quantity precondition property must declare a canonical unit",
    ):
        InstrumentDescription(
            instrument_id="source-0",
            implementation_id="tests.dimension_only_precondition",
            implementation_version="v1",
            interfaces=[
                interface(
                    source.interface_id,
                    properties=[
                        PropertySpec(
                            id=level.property_id,
                            value_type=Scalar(QuantityType(dimension="voltage")),
                        )
                    ],
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("reading", unit="V")],
                            preconditions=[
                                acquisition_precondition(
                                    level,
                                    value=Quantity(1.0, "V"),
                                    unavailable_reason="Level is not one volt.",
                                )
                            ],
                        )
                    ],
                )
            ],
        )


def test_quantity_preconditions_compare_projected_compatible_units() -> None:
    level = InterfaceRef("test.level/v1").property("level")
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.quantity_precondition",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.level/v1",
                properties=[quantity_property("level", unit="V")],
                acquisitions=[
                    acquisition(
                        "sample",
                        results=[acquisition_result("reading", unit="V")],
                        preconditions=[
                            acquisition_precondition(
                                level,
                                value=Quantity(1.0, "V"),
                                unavailable_reason="Level is not one volt.",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    baseline = InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.level/v1",
                property_id="level",
                value=StateValue(Quantity(0.0, "V")),
            )
        ],
    )
    projection = project_instrument_state(
        baseline,
        InstrumentStateCommand(
            command_id="set-level",
            instrument_id="source-0",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="source-0",
                    interface_id="test.level/v1",
                    property_id="level",
                    value=StateValue(Quantity(1_000.0, "mV")),
                )
            ],
        ),
        description=description,
    )
    command = CollectCommand(
        command_id="collect-level",
        instrument_id="source-0",
        point_index=0,
        point_count=1,
        requests=[
            CollectResultRequest(
                id="reading",
                interface_id="test.level/v1",
                acquisition_id="sample",
                result_id="reading",
                unit="V",
            )
        ],
    )

    assert (
        validate_collect_plan(
            command=command,
            description=description,
            baseline=projection,
        )
        == []
    )


def test_precondition_literals_have_canonical_contract_fingerprints() -> None:
    level = InterfaceRef("test.level/v1").property("level")

    def describe(
        value: float | Quantity,
        property_spec: PropertySpec,
    ) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id="source-0",
            implementation_id="tests.canonical_precondition",
            implementation_version="v1",
            interfaces=[
                interface(
                    level.interface_id,
                    properties=[property_spec],
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("reading")],
                            preconditions=[
                                acquisition_precondition(
                                    level,
                                    value=value,
                                    unavailable_reason="Level differs.",
                                )
                            ],
                        )
                    ],
                )
            ],
        )

    integer_float = describe(1, float_property("level"))
    explicit_float = describe(1.0, float_property("level"))
    negative_zero = describe(
        Quantity(-0.0, "V"),
        quantity_property("level", unit="V"),
    )
    positive_zero = describe(
        Quantity(0.0, "V"),
        quantity_property("level", unit="V"),
    )

    assert integer_float.model_dump_json() == explicit_float.model_dump_json()
    assert negative_zero.model_dump_json() == positive_zero.model_dump_json()
    assert instrument_contract_fingerprint(
        "tests",
        (integer_float,),
    ) == instrument_contract_fingerprint("tests", (explicit_float,))
    assert instrument_contract_fingerprint(
        "tests",
        (negative_zero,),
    ) == instrument_contract_fingerprint("tests", (positive_zero,))


def test_description_normalization_owns_shared_interface_models() -> None:
    level = InterfaceRef("test.shared_level/v1").property("level")
    shared_acquisition = acquisition(
        "sample",
        results=[acquisition_result("reading")],
        preconditions=[
            acquisition_precondition(
                level,
                value=1,
                unavailable_reason="Level differs.",
            )
        ],
    )
    integer_interface = interface(
        level.interface_id,
        properties=[int_property("level")],
        acquisitions=[shared_acquisition],
    )
    float_interface = interface(
        level.interface_id,
        properties=[float_property("level")],
        acquisitions=[shared_acquisition],
    )
    integer_description = InstrumentDescription(
        instrument_id="integer-source",
        implementation_id="tests.shared_precondition",
        implementation_version="v1",
        interfaces=[integer_interface],
    )
    original_fingerprint = instrument_contract_fingerprint(
        "tests",
        (integer_description,),
    )

    float_description = InstrumentDescription(
        instrument_id="float-source",
        implementation_id="tests.shared_precondition",
        implementation_version="v1",
        interfaces=[float_interface],
    )

    assert (
        instrument_contract_fingerprint(
            "tests",
            (integer_description,),
        )
        == original_fingerprint
    )
    assert type(shared_acquisition.preconditions[0].value) is int
    assert (
        type(integer_description.interfaces[0].acquisitions[0].preconditions[0].value)
        is int
    )
    assert (
        type(float_description.interfaces[0].acquisitions[0].preconditions[0].value)
        is float
    )
    assert (
        InstrumentDescription.model_validate_json(integer_description.model_dump_json())
        == integer_description
    )


def test_instrument_ints_are_bounded_by_the_json_safe_range() -> None:
    safe_limit = (1 << 53) - 1
    count = InterfaceRef("test.counter/v1").property("count")
    property_spec = int_property("count")
    assert isinstance(property_spec.value_type.atom, Int)
    assert property_spec.value_type.atom.minimum == -safe_limit
    assert property_spec.value_type.atom.maximum == safe_limit

    with pytest.raises(
        ValidationError,
        match="JSON safe integer range",
    ):
        int_property("count", maximum=safe_limit + 1)

    with pytest.raises(
        ValidationError,
        match="at most",
    ):
        InstrumentDescription(
            instrument_id="counter-0",
            implementation_id="tests.counter",
            implementation_version="v1",
            interfaces=[
                interface(
                    count.interface_id,
                    properties=[property_spec],
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("reading")],
                            preconditions=[
                                acquisition_precondition(
                                    count,
                                    value=safe_limit + 1,
                                    unavailable_reason="Count differs.",
                                )
                            ],
                        )
                    ],
                )
            ],
        )


def test_numeric_property_bounds_have_canonical_interface_wire() -> None:
    negative_zero = InstrumentDescription(
        instrument_id="source-negative",
        implementation_id="tests.quantity_bounds",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.quantity_bounds/v1",
                properties=[quantity_property("level", unit="V", minimum=-0.0)],
            )
        ],
    )
    positive_zero = InstrumentDescription(
        instrument_id="source-positive",
        implementation_id="tests.quantity_bounds",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.quantity_bounds/v1",
                properties=[quantity_property("level", unit="V", minimum=0.0)],
            )
        ],
    )

    assert (
        negative_zero.interfaces[0].model_dump_json()
        == positive_zero.interfaces[0].model_dump_json()
    )
    validate_instrument_description_collection((negative_zero, positive_zero))


def test_discriminated_state_builder_owns_its_property_partition() -> None:
    with pytest.raises(
        ValueError,
        match="properties must be declared by the state",
    ):
        interface(
            "test.dc/v1",
            properties=[float_property("level")],
            state=discriminated_state(
                enum_property("mode", choices=("voltage", "current")),
                cases=(
                    state_case("voltage"),
                    state_case("current"),
                ),
            ),
        )

    with pytest.raises(ValidationError, match="choices exactly match case values"):
        interface(
            "test.dc/v1",
            state=discriminated_state(
                enum_property("mode", choices=("voltage", "current")),
                cases=(
                    state_case("current"),
                    state_case("voltage"),
                ),
            ),
        )


def test_state_case_entry_requirements_are_declared_members_and_writable() -> None:
    with pytest.raises(
        ValidationError,
        match="entry requirements reference unknown properties",
    ):
        interface(
            "test.dc/v1",
            state=discriminated_state(
                enum_property("mode", choices=("voltage", "current")),
                cases=(
                    state_case(
                        "voltage",
                        properties=(float_property("voltage_level"),),
                        required_on_entry_property_ids=("missing",),
                    ),
                    state_case("current"),
                ),
            ),
        )

    with pytest.raises(
        ValidationError,
        match="entry requirements must be writable",
    ):
        interface(
            "test.dc/v1",
            state=discriminated_state(
                enum_property("mode", choices=("voltage", "current")),
                cases=(
                    state_case(
                        "voltage",
                        properties=(
                            float_property("voltage_level", access="read_only"),
                        ),
                        required_on_entry_property_ids=("voltage_level",),
                    ),
                    state_case("current"),
                ),
            ),
        )


def test_state_command_uses_observed_discriminator_for_partial_patches() -> None:
    description = _variant_description()
    voltage = _variant_snapshot("voltage", "voltage_level", 0.1)
    current = _variant_snapshot("current", "current_level", 0.01)
    voltage_patch = _variant_command(("voltage_level", 0.2))

    assert (
        validate_state_command(
            command=voltage_patch,
            description=description,
            baseline=voltage,
        )
        == []
    )
    assert [
        item.code
        for item in validate_state_command(
            command=voltage_patch,
            description=description,
            baseline=current,
        )
    ] == ["instrument_driver_state_case_mismatch"]


def test_state_command_requires_a_complete_case_without_a_matching_baseline() -> None:
    description = _variant_description()
    voltage = _variant_snapshot("voltage", "voltage_level", 0.1)
    incomplete_switch = _variant_command(("mode", "current"))
    incomplete_without_baseline = _variant_command(("current_level", 0.02))

    without_baseline = validate_state_command(
        command=incomplete_without_baseline,
        description=description,
    )
    switching_case = validate_state_command(
        command=incomplete_switch,
        description=description,
        baseline=voltage,
    )

    assert [item.code for item in without_baseline] == [
        "instrument_driver_state_case_incomplete"
    ]
    assert [item.code for item in switching_case] == [
        "instrument_driver_state_case_incomplete"
    ]
    assert "current_range" in without_baseline[0].message
    assert "current_level" in switching_case[0].message


def test_state_command_allows_complete_switches_and_sparse_same_case_patches() -> None:
    description = _variant_description()
    voltage = _variant_snapshot("voltage", "voltage_level", 0.1)
    current = _variant_snapshot("current", "current_level", 0.01)
    complete_switch = _variant_command(
        ("mode", "current"),
        ("current_range", 0.1),
        ("current_level", 0.02),
    )

    assert (
        validate_state_command(
            command=complete_switch,
            description=description,
        )
        == []
    )
    assert (
        validate_state_command(
            command=complete_switch,
            description=description,
            baseline=voltage,
        )
        == []
    )
    assert (
        validate_state_command(
            command=_variant_command(("mode", "current")),
            description=description,
            baseline=current,
        )
        == []
    )


def test_state_command_only_requires_properties_declared_for_case_entry() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.explicit_case_entry",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.dc/v1",
                state=discriminated_state(
                    enum_property("mode", choices=("voltage", "current")),
                    cases=(
                        state_case(
                            "voltage",
                            properties=(
                                float_property("voltage_range"),
                                float_property("voltage_level"),
                            ),
                            required_on_entry_property_ids=("voltage_level",),
                        ),
                        state_case(
                            "current",
                            properties=(
                                float_property("current_range"),
                                float_property("current_level"),
                            ),
                            required_on_entry_property_ids=("current_level",),
                        ),
                    ),
                ),
            )
        ],
    )
    switch = _variant_command(
        ("mode", "current"),
        ("current_level", 0.02),
    )

    assert validate_state_command(command=switch, description=description) == []


def test_state_command_uses_physical_discriminator_across_logical_targets() -> None:
    description = _variant_description()
    baseline = InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="mode",
                value=StateValue("current"),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="current_range",
                value=StateValue(0.1),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="current_level",
                value=StateValue(0.01),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="output_enabled",
                value=StateValue(False),
            ),
        ],
    )
    patch = InstrumentStateCommand(
        command_id="scoped-patch",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.dc/v1",
                property_id="current_level",
                value=StateValue(0.02),
                entity_ids=["channel-b"],
            )
        ],
    )

    assert (
        validate_state_command(
            command=patch,
            description=description,
            baseline=baseline,
        )
        == []
    )


def test_state_command_can_require_an_explicit_discriminator() -> None:
    patch = _variant_command(("current_level", 0.02))

    [problem] = validate_state_command(
        command=patch,
        description=_variant_description(),
        require_explicit_state_case=True,
    )

    assert problem.code == "instrument_driver_state_case_unknown"
    assert isinstance(problem.related_locations[0], ModelLocation)
    assert problem.related_locations[0].path == ("test.dc/v1", "mode")


def test_state_command_rejects_duplicate_physical_targets() -> None:
    with pytest.raises(
        ValidationError,
        match="instrument state command property targets must be unique",
    ):
        InstrumentStateCommand(
            command_id="duplicate-physical-target",
            instrument_id="source-0",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="source-0",
                    interface_id="test.dc/v1",
                    property_id="output_enabled",
                    value=StateValue(False),
                    entity_ids=["channel-a"],
                ),
                InstrumentStateAssignment(
                    resource_id="source-0",
                    interface_id="test.dc/v1",
                    property_id="output_enabled",
                    value=StateValue(False),
                    entity_ids=["channel-b"],
                ),
            ],
        )


def test_state_command_rejects_mixed_or_explicitly_mismatched_cases() -> None:
    description = _variant_description()

    mixed = validate_state_command(
        command=_variant_command(
            ("voltage_level", 0.2),
            ("current_level", 0.01),
        ),
        description=description,
    )
    explicit_mismatch = validate_state_command(
        command=_variant_command(
            ("mode", "current"),
            ("voltage_level", 0.2),
        ),
        description=description,
    )

    assert [item.code for item in mixed] == ["instrument_driver_mixed_state_cases"]
    assert [item.code for item in explicit_mismatch] == [
        "instrument_driver_state_case_mismatch"
    ]


def test_instrument_property_state_contains_only_a_physical_target() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RecordInstrumentPropertyState.model_validate(
            {
                "interface_id": "test.control/v1",
                "property_id": "gain",
                "value": 1.0,
                "entity_ids": ["logical-channel"],
            }
        )


def test_state_snapshot_requires_every_static_observable_scope() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.static_state",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.control/v1",
                properties=[
                    float_property("gain"),
                    string_property("secret", access="write_only"),
                ],
                components=[
                    component(
                        "channel-a",
                        properties=[
                            bool_property("enabled", access="read_only"),
                        ],
                    )
                ],
            )
        ],
    )
    empty = InstrumentStateSnapshot(instrument_id="source-0")

    assert [
        item.code
        for item in validate_state_snapshot(
            snapshot=empty,
            description=description,
        )
    ] == [
        "instrument_driver_snapshot_missing_properties",
        "instrument_driver_snapshot_missing_properties",
    ]

    complete = InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.control/v1",
                property_id="gain",
                value=StateValue(1.0),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.control/v1",
                component_path=["channel-a"],
                property_id="enabled",
                value=StateValue(True),
            ),
        ],
    )
    assert (
        validate_state_snapshot(
            snapshot=complete,
            description=description,
        )
        == []
    )

    with_write_only = complete.model_copy(
        update={
            "properties": [
                *complete.properties,
                RecordInstrumentPropertyState(
                    interface_id="test.control/v1",
                    property_id="secret",
                    value=StateValue("returned-secret"),
                ),
            ]
        }
    )
    assert [
        item.code
        for item in validate_state_snapshot(
            snapshot=with_write_only,
            description=description,
        )
    ] == ["instrument_driver_snapshot_write_only_property"]


def test_state_snapshot_requires_declared_quantity_units() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.canonical_snapshot_units",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.source/v1",
                properties=[quantity_property("frequency", unit="GHz")],
            )
        ],
    )
    snapshot = InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.source/v1",
                property_id="frequency",
                value=StateValue(Quantity(5_000.0, "MHz")),
            )
        ],
    )

    [problem] = validate_state_snapshot(
        snapshot=snapshot,
        description=description,
    )
    assert problem.code == "instrument_driver_snapshot_property_value_mismatch"
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.path == ("properties", 0, "value", "unit")


def test_discriminated_snapshot_requires_common_and_active_case_state() -> None:
    incomplete = InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="mode",
                value=StateValue("voltage"),
            )
        ],
    )

    [missing] = validate_state_snapshot(
        snapshot=incomplete,
        description=_variant_description(),
    )

    assert missing.code == "instrument_driver_snapshot_missing_properties"
    assert "output_enabled" in missing.message
    assert "voltage_level" in missing.message
    assert {
        location.path
        for location in missing.related_locations
        if isinstance(location, ModelLocation)
    } == {
        ("test.dc/v1", "output_enabled"),
        ("test.dc/v1", "voltage_level"),
        ("test.dc/v1", "voltage_range"),
    }


def test_state_snapshot_and_projection_preserve_one_active_case() -> None:
    description = _variant_description()
    voltage = _variant_snapshot("voltage", "voltage_level", 0.1)
    invalid = voltage.model_copy(
        update={
            "properties": [
                *voltage.properties,
                RecordInstrumentPropertyState(
                    interface_id="test.dc/v1",
                    property_id="current_level",
                    value=StateValue(0.01),
                ),
            ]
        }
    )

    [inactive] = validate_state_snapshot(
        snapshot=invalid,
        description=description,
    )
    assert inactive.code == "instrument_driver_snapshot_inactive_state_property"
    assert isinstance(inactive.related_locations[0], ModelLocation)
    assert inactive.related_locations[0].path == (
        "test.dc/v1",
        "current_level",
    )

    switched = project_instrument_state(
        voltage,
        _variant_command(
            ("mode", "current"),
            ("current_range", 0.1),
            ("current_level", 0.02),
        ),
        description=description,
    )
    properties = {item.property_id: item.value.root for item in switched.properties}
    assert properties == {
        "current_level": 0.02,
        "current_range": 0.1,
        "mode": "current",
        "output_enabled": False,
    }
    observed = InstrumentStateSnapshot(
        instrument_id=switched.instrument_id,
        properties=list(switched.properties),
    )
    assert validate_state_snapshot(snapshot=observed, description=description) == []


def _interactive_collect_intent(
    *,
    command_id: str = "collect-signal",
    instrument_id: str = "source-0",
    interface_id: str = "test.trace/v1",
    component_path: tuple[str, ...] = (),
    acquisition_id: str = "sample",
    result_ids: tuple[str, ...] = (),
) -> InteractiveCollectIntent:
    return InteractiveCollectIntent(
        command_id=command_id,
        instrument_id=instrument_id,
        interface_id=interface_id,
        component_path=list(component_path),
        acquisition_id=acquisition_id,
        result_ids=list(result_ids),
    )


def _interactive_monitor_intent(
    *,
    command_id: str,
    result_ids: tuple[str, ...] = (),
) -> InteractiveCollectIntent:
    return InteractiveCollectIntent(
        command_id=command_id,
        instrument_id="source-0",
        interface_id="test.monitor/v1",
        acquisition_id="monitor",
        result_ids=list(result_ids),
    )


def test_acquisition_result_rejects_duplicate_axis_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="acquisition result axis ids must be unique",
    ):
        acquisition_result(
            "signal",
            axes=[
                acquisition_axis("frequency", size=3, kind="frequency"),
                acquisition_axis("frequency", size=3, kind="frequency"),
            ],
        )


def test_interactive_collect_intent_requires_unique_result_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="interactive collect result ids must be unique",
    ):
        InteractiveCollectIntent(
            command_id="collect-duplicate",
            instrument_id="source-0",
            interface_id="test.trace/v1",
            acquisition_id="sample",
            result_ids=["signal", "signal"],
        )


def test_interactive_collect_resolves_all_or_explicit_fixed_results() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.interactive_collect",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.trace/v1",
                acquisitions=[
                    acquisition(
                        "sample",
                        results=[
                            acquisition_result("signal", unit="V"),
                            acquisition_result("phase", unit="rad"),
                        ],
                    )
                ],
            )
        ],
    )
    state = InstrumentStateSnapshot(instrument_id="source-0")

    all_results = resolve_interactive_collect(
        intent=_interactive_collect_intent(command_id="collect-all"),
        description=description,
        state=state,
    )
    explicit = resolve_interactive_collect(
        intent=_interactive_collect_intent(
            command_id="collect-phase",
            result_ids=("phase",),
        ),
        description=description,
        state=state,
    )

    assert isinstance(all_results, ResolvedInteractiveCollect)
    assert all_results.command.point_index == 0
    assert all_results.command.point_count == 1
    assert [
        (request.id, request.result_id, request.unit)
        for request in all_results.command.requests
    ] == [
        ("signal", "signal", "V"),
        ("phase", "phase", "rad"),
    ]
    assert isinstance(explicit, ResolvedInteractiveCollect)
    assert [request.result_id for request in explicit.command.requests] == ["phase"]
    assert (
        validate_collect_plan(
            command=explicit.command,
            description=description,
            baseline=state,
        )
        == []
    )


@pytest.mark.parametrize(
    ("intent", "code", "path"),
    [
        (
            _interactive_collect_intent(instrument_id="other"),
            "instrument_driver_mismatch",
            ("instrument_id",),
        ),
        (
            _interactive_collect_intent(interface_id="test.missing/v1"),
            "instrument_driver_unsupported_interface",
            ("interface_id",),
        ),
        (
            _interactive_collect_intent(component_path=("missing",)),
            "instrument_driver_unsupported_component",
            ("component_path",),
        ),
        (
            _interactive_collect_intent(acquisition_id="missing"),
            "instrument_driver_unsupported_acquisition",
            ("acquisition_id",),
        ),
        (
            _interactive_collect_intent(result_ids=("missing",)),
            "instrument_driver_unsupported_acquisition_result",
            ("result_ids", 0),
        ),
    ],
    ids=("instrument", "interface", "component", "acquisition", "result"),
)
def test_interactive_collect_rejects_unsupported_targets(
    intent: InteractiveCollectIntent,
    code: str,
    path: tuple[str | int, ...],
) -> None:
    resolution = resolve_interactive_collect(
        intent=intent,
        description=_collect_description(),
        state=InstrumentStateSnapshot(instrument_id="source-0"),
    )

    assert isinstance(resolution, RejectedInteractiveCollect)
    [problem] = resolution.problems
    assert problem.code == code
    assert problem.location == ModelLocation(
        root="interactive_collect_intent",
        path=path,
    )


def test_interactive_collect_selects_the_fresh_discriminated_results() -> None:
    description = _state_discriminated_collect_description()
    voltage = resolve_interactive_collect(
        intent=_interactive_monitor_intent(command_id="collect-voltage"),
        description=description,
        state=_state_discriminated_collect_snapshot("voltage"),
    )
    current = resolve_interactive_collect(
        intent=_interactive_monitor_intent(command_id="collect-current"),
        description=description,
        state=_state_discriminated_collect_snapshot("current"),
    )

    assert isinstance(voltage, ResolvedInteractiveCollect)
    assert isinstance(current, ResolvedInteractiveCollect)
    assert [request.result_id for request in voltage.command.requests] == [
        "monitored_current"
    ]
    assert [request.result_id for request in current.command.requests] == [
        "monitored_voltage"
    ]


def test_interactive_collect_reports_inactive_results_and_blocked_state() -> None:
    description = _state_discriminated_collect_description()
    inactive = resolve_interactive_collect(
        intent=_interactive_monitor_intent(
            command_id="collect-inactive",
            result_ids=("monitored_voltage",),
        ),
        description=description,
        state=_state_discriminated_collect_snapshot("voltage"),
    )
    blocked_description = _state_discriminated_collect_description(
        preconditions=(
            acquisition_precondition(
                InterfaceRef("test.source/v1")
                .component("output")
                .property("output_enabled"),
                value=True,
                unavailable_reason="Source output is disabled.",
            ),
        )
    )
    blocked = resolve_interactive_collect(
        intent=_interactive_monitor_intent(command_id="collect-blocked"),
        description=blocked_description,
        state=_state_discriminated_collect_snapshot("voltage"),
    )

    assert isinstance(inactive, RejectedInteractiveCollect)
    [inactive_problem] = inactive.problems
    assert inactive_problem.code == "instrument_driver_inactive_acquisition_result"
    assert inactive_problem.location == ModelLocation(
        root="interactive_collect_intent",
        path=("result_ids", 0),
    )
    assert inactive_problem.details == {
        "result_id": "monitored_voltage",
        "active_case": "voltage",
    }
    assert isinstance(blocked, RejectedInteractiveCollect)
    assert [problem.code for problem in blocked.problems] == [
        "instrument_driver_acquisition_precondition_not_met"
    ]
    assert blocked.problems[0].related_locations == (
        ModelLocation(
            root="instrument_state",
            path=("test.source/v1", "output", "output_enabled"),
        ),
    )


def test_interactive_collect_reports_unknown_discriminator_state() -> None:
    resolution = resolve_interactive_collect(
        intent=_interactive_monitor_intent(command_id="collect-unknown"),
        description=_state_discriminated_collect_description(),
        state=InstrumentStateSnapshot(instrument_id="source-0"),
    )

    assert isinstance(resolution, RejectedInteractiveCollect)
    [problem] = resolution.problems
    assert problem.code == "instrument_driver_acquisition_state_unknown"
    assert problem.location == ModelLocation(
        root="interactive_collect_intent",
        path=("acquisition_id",),
    )
    assert problem.related_locations == (
        ModelLocation(
            root="instrument_state",
            path=("test.source/v1", "output", "mode"),
        ),
    )


def test_interactive_collect_freezes_state_sized_axes() -> None:
    description = _state_sized_collect_description()
    resolved = resolve_interactive_collect(
        intent=_interactive_collect_intent(command_id="collect-sized"),
        description=description,
        state=_state_sized_collect_snapshot(17),
    )
    unresolved = resolve_interactive_collect(
        intent=_interactive_collect_intent(command_id="collect-unsized"),
        description=description,
        state=InstrumentStateSnapshot(instrument_id="other"),
    )

    assert isinstance(resolved, ResolvedInteractiveCollect)
    assert resolved.command.requests[0].dimensions == [
        CollectAxisRequest(id="channel", kind="channel", size=2),
        CollectAxisRequest(
            id="frequency",
            kind="frequency",
            size=17,
            unit="Hz",
        ),
    ]
    assert isinstance(unresolved, RejectedInteractiveCollect)
    [problem] = unresolved.problems
    assert problem.code == "instrument_driver_acquisition_axis_state_unknown"
    assert problem.location == ModelLocation(
        root="interactive_collect_intent",
        path=("acquisition_id",),
    )
    assert problem.related_locations == (
        ModelLocation(
            root="instrument_state",
            path=("test.sweep/v1", "points"),
        ),
    )
    assert problem.details == {
        "result_id": "signal",
        "axis_id": "frequency",
        "axis_index": 1,
        "state_property": {
            "interface_id": "test.sweep/v1",
            "component_path": (),
            "property_id": "points",
        },
    }


def test_acquisition_axis_requires_an_explicit_size_contract() -> None:
    serialized = _collect_description().model_dump(mode="json")
    del serialized["interfaces"][0]["acquisitions"][0]["results"][0]["axes"][0]["size"]

    with pytest.raises(ValidationError, match="Field required"):
        InstrumentDescription.model_validate(serialized)


def test_state_sized_axis_has_canonical_wire_and_fingerprint() -> None:
    description = _state_sized_collect_description()
    result = acquisition_results(description.interfaces[1].acquisitions[0])[0]
    axis = result.axes[1]
    serialized = description.model_dump(mode="json")
    restored = InstrumentDescription.model_validate(serialized)

    assert isinstance(axis.size, StatePropertyRef)
    assert serialized["interfaces"][1]["acquisitions"][0]["results"][0]["axes"][1][
        "size"
    ] == {
        "interface_id": "test.sweep/v1",
        "component_path": [],
        "property_id": "points",
    }
    assert instrument_contract_fingerprint(
        "tests",
        (description,),
    ) == instrument_contract_fingerprint("tests", (restored,))


@pytest.mark.parametrize(
    ("property_spec", "size_reference", "message"),
    [
        (
            int_property("points", minimum=1),
            InterfaceRef("test.sweep/v1").property("missing"),
            "size must reference a declared property",
        ),
        (
            int_property("points", minimum=1, access="write_only"),
            InterfaceRef("test.sweep/v1").property("points"),
            "size property must be observable",
        ),
        (
            float_property("points"),
            InterfaceRef("test.sweep/v1").property("points"),
            "size property must be an integer",
        ),
        (
            int_property("points", minimum=0),
            InterfaceRef("test.sweep/v1").property("points"),
            "size property must have a positive minimum",
        ),
    ],
    ids=("missing", "write-only", "non-integer", "non-positive-minimum"),
)
def test_state_sized_axis_rejects_invalid_property_references(
    property_spec: PropertySpec,
    size_reference: PropertyRef,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _state_sized_collect_description(
            property_spec=property_spec,
            size_reference=size_reference,
        )


def test_state_sized_axis_must_be_visible_in_its_acquisition_case() -> None:
    trace = InterfaceRef("test.trace/v1")

    with pytest.raises(
        ValidationError,
        match=r"case 'voltage'.*size references state that is not always observable",
    ):
        InstrumentDescription(
            instrument_id="source-0",
            implementation_id="tests.case_sized_axis",
            implementation_version="v1",
            interfaces=[
                interface(
                    trace.interface_id,
                    state=discriminated_state(
                        enum_property("mode", choices=("voltage", "current")),
                        cases=(
                            state_case(
                                "voltage",
                                properties=(int_property("voltage_points", minimum=1),),
                            ),
                            state_case(
                                "current",
                                properties=(int_property("current_points", minimum=1),),
                            ),
                        ),
                    ),
                    acquisitions=[
                        state_discriminated_acquisition(
                            "sample",
                            discriminator=trace.property("mode"),
                            cases=(
                                acquisition_case(
                                    "voltage",
                                    results=(
                                        acquisition_result(
                                            "voltage_signal",
                                            axes=(
                                                acquisition_axis(
                                                    "frequency",
                                                    size=trace.property(
                                                        "current_points"
                                                    ),
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                                acquisition_case(
                                    "current",
                                    results=(
                                        acquisition_result(
                                            "current_signal",
                                            axes=(
                                                acquisition_axis(
                                                    "frequency",
                                                    size=1,
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        )
                    ],
                )
            ],
        )


def test_mixed_fixed_and_state_sized_axes_resolve_from_one_snapshot() -> None:
    description = _state_sized_collect_description()
    result = acquisition_results(description.interfaces[1].acquisitions[0])[0]
    command = _state_sized_collect_command(17)

    assert (
        resolve_acquisition_dimensions(
            description=description,
            result=result,
            state=None,
        )
        is None
    )
    assert resolve_acquisition_dimensions(
        description=description,
        result=result,
        state=_state_sized_collect_snapshot(17),
    ) == tuple(command.requests[0].dimensions)
    assert validate_collect_command(command=command, description=description) == []


def test_collect_plan_checks_state_sized_axes_at_the_exact_state_target() -> None:
    description = _state_sized_collect_description()
    command = _state_sized_collect_command(17)

    [unknown] = validate_collect_plan(
        command=command,
        description=description,
        baseline=None,
    )
    matching = validate_collect_plan(
        command=command,
        description=description,
        baseline=_state_sized_collect_snapshot(17),
    )
    [mismatch] = validate_collect_plan(
        command=command,
        description=description,
        baseline=_state_sized_collect_snapshot(19),
    )

    location = ModelLocation(
        root="instrument_collect_command",
        path=("requests", "signal", "dimensions", 1, "size"),
    )
    related = (
        ModelLocation(
            root="instrument_state",
            path=("test.sweep/v1", "points"),
        ),
    )
    assert unknown.code == "instrument_driver_acquisition_axis_state_unknown"
    assert unknown.location == location
    assert unknown.related_locations == related
    assert unknown.details == {
        "state_property": {
            "interface_id": "test.sweep/v1",
            "component_path": (),
            "property_id": "points",
        },
        "requested_size": 17,
    }
    assert matching == []
    assert mismatch.code == "instrument_driver_acquisition_axis_state_mismatch"
    assert mismatch.location == location
    assert mismatch.related_locations == related
    assert mismatch.details == {
        **unknown.details,
        "observed_value": 19,
    }


def test_collect_validator_reports_unsupported_result_without_crashing() -> None:
    problems = validate_collect_command(
        command=CollectCommand(
            command_id="unsupported-result",
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


def test_collect_validator_accepts_compatible_units_and_fixed_shapes() -> None:
    problems = validate_collect_command(
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

    assert problems == []


def test_collect_validator_requires_every_declared_axis() -> None:
    [problem] = validate_collect_command(
        command=_collect_command(unit=None, dimensions=[]),
        description=_collect_description(),
    )

    assert problem.code == "instrument_driver_acquisition_axes_mismatch"


def test_collect_validator_checks_dtype_unit_and_axis_contracts() -> None:
    problems = validate_collect_command(
        command=_collect_command(
            dtype="int64",
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


def test_state_discriminated_collect_requires_a_complete_observed_state() -> None:
    description = _state_discriminated_collect_description()
    command = _state_discriminated_collect_command(
        "monitored_current",
        unit="A",
    )

    missing = validate_collect_plan(
        command=command,
        description=description,
        baseline=None,
    )
    incomplete = validate_collect_plan(
        command=command,
        description=description,
        baseline=InstrumentStateSnapshot(
            instrument_id="source-0",
            properties=[
                RecordInstrumentPropertyState(
                    interface_id="test.source/v1",
                    component_path=["output"],
                    property_id="mode",
                    value=StateValue("voltage"),
                )
            ],
        ),
    )

    assert [problem.code for problem in missing] == [
        "instrument_driver_acquisition_state_unknown"
    ]
    assert [problem.code for problem in incomplete] == [
        "instrument_driver_acquisition_state_unknown"
    ]
    assert isinstance(missing[0].related_locations[0], ModelLocation)
    assert missing[0].related_locations[0].path == (
        "test.source/v1",
        "output",
        "mode",
    )


def test_state_discriminated_collect_allows_only_the_active_case_results() -> None:
    description = _state_discriminated_collect_description()
    baseline = _state_discriminated_collect_snapshot("voltage")

    active = validate_collect_plan(
        command=_state_discriminated_collect_command(
            "monitored_current",
            unit="A",
        ),
        description=description,
        baseline=baseline,
    )
    inactive = validate_collect_plan(
        command=_state_discriminated_collect_command(
            "monitored_voltage",
            unit="V",
        ),
        description=description,
        baseline=baseline,
    )

    assert active == []
    assert [problem.code for problem in inactive] == [
        "instrument_driver_inactive_acquisition_result"
    ]


def test_partial_projection_drives_conditional_state_and_collect_preflight() -> None:
    description = _state_discriminated_collect_description()
    select_voltage = InstrumentStateCommand(
        command_id="select-voltage",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.source/v1",
                component_path=["output"],
                property_id="mode",
                value=StateValue("voltage"),
            )
        ],
    )
    projection = project_instrument_state(
        ProjectedInstrumentState(instrument_id="source-0"),
        select_voltage,
        description=description,
    )
    observed = InstrumentStateSnapshot(
        instrument_id=projection.instrument_id,
        properties=list(projection.properties),
    )
    set_voltage = InstrumentStateCommand(
        command_id="set-voltage",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.source/v1",
                component_path=["output"],
                property_id="voltage_level",
                value=StateValue(0.2),
            )
        ],
    )

    assert isinstance(projection.properties, tuple)
    assert not hasattr(projection, "model_dump")
    assert [item.property_id for item in projection.properties] == ["mode"]
    assert [
        problem.code
        for problem in validate_state_snapshot(
            snapshot=observed,
            description=description,
        )
    ] == ["instrument_driver_snapshot_missing_properties"]
    assert (
        validate_state_command(
            command=set_voltage,
            description=description,
            baseline=projection,
            require_explicit_state_case=True,
        )
        == []
    )
    assert (
        validate_collect_plan(
            command=_state_discriminated_collect_command(
                "monitored_current",
                unit="A",
            ),
            description=description,
            baseline=projection,
        )
        == []
    )


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
                    "signal": MeasurementArray.create(
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
                    "unexpected": MeasurementArray.create(
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
                    "signal": MeasurementArray.create(
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


@pytest.mark.parametrize(
    "value",
    (
        MeasurementArray.create(
            dtype="float64",
            unit="Hz",
            shape=(3,),
            values=(1.0, 2.0, 3.0),
        ),
        MeasurementUnavailable.create(
            reason="overload",
            dtype="float64",
            unit="Hz",
            shape=(3,),
            metadata={"instrument_status": "adc overload"},
        ),
    ),
    ids=("available", "unavailable"),
)
def test_collect_receipt_enforces_the_concrete_requested_shape(
    value: MeasurementArray | MeasurementUnavailable,
) -> None:
    def validate(size: int) -> list[Problem]:
        return validate_collect_receipt(
            command=_collect_command(
                dimensions=[
                    CollectAxisRequest(
                        id="frequency",
                        kind="frequency",
                        size=size,
                        unit="Hz",
                    )
                ]
            ),
            receipt=CollectReceipt(
                readback=RecordInstrumentReadback(values={"signal": value})
            ),
        )

    assert validate(3) == []
    assert [problem.code for problem in validate(2)] == [
        "instrument_driver_readback_shape_mismatch"
    ]


def test_run_accepts_instrument_driver(tmp_path: Path) -> None:
    instrument = SignalInstrumentDriver()

    manifest = execute_bound_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert len(instrument.collect_requests) == 3
    assert [result.result_id for result in instrument.collect_requests[0].results] == [
        "signal"
    ]
    assert next(iter(instrument.applied[0].values)).interface_id == (
        "test.set_frequency/v1"
    )


def _state_command(
    *,
    interface_id: str,
    property_id: str,
    value: StateValue,
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        command_id="state-command",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id=interface_id,
                property_id=property_id,
                value=value,
            )
        ],
    )


def _variant_description() -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.variant",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.dc/v1",
                state=discriminated_state(
                    enum_property("mode", choices=("voltage", "current")),
                    common_properties=(bool_property("output_enabled"),),
                    cases=(
                        state_case(
                            "voltage",
                            properties=(
                                float_property("voltage_range"),
                                float_property("voltage_level"),
                            ),
                            required_on_entry_property_ids=(
                                "voltage_range",
                                "voltage_level",
                            ),
                        ),
                        state_case(
                            "current",
                            properties=(
                                float_property("current_range"),
                                float_property("current_level"),
                            ),
                            required_on_entry_property_ids=(
                                "current_range",
                                "current_level",
                            ),
                        ),
                    ),
                ),
            )
        ],
    )


def _variant_snapshot(
    mode: str,
    property_id: str,
    value: float,
) -> InstrumentStateSnapshot:
    range_property_id = "voltage_range" if mode == "voltage" else "current_range"
    return InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="mode",
                value=StateValue(mode),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id=range_property_id,
                value=StateValue(1.0),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id=property_id,
                value=StateValue(value),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.dc/v1",
                property_id="output_enabled",
                value=StateValue(False),
            ),
        ],
    )


def _variant_command(
    *assignments: tuple[str, str | float],
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        command_id="variant-command",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.dc/v1",
                property_id=property_id,
                value=StateValue(value),
            )
            for property_id, value in assignments
        ],
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
                                        size=17,
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


def _state_sized_collect_description(
    *,
    property_spec: PropertySpec | None = None,
    size_reference: PropertyRef | None = None,
) -> InstrumentDescription:
    sweep = InterfaceRef("test.sweep/v1")
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.state_sized_collect",
        implementation_version="v1",
        interfaces=[
            interface(
                sweep.interface_id,
                properties=[
                    property_spec or int_property("points", minimum=1),
                ],
            ),
            interface(
                "test.trace/v1",
                acquisitions=[
                    acquisition(
                        "sample",
                        results=[
                            acquisition_result(
                                "signal",
                                unit="Hz",
                                axes=[
                                    acquisition_axis(
                                        "channel",
                                        size=2,
                                    ),
                                    acquisition_axis(
                                        "frequency",
                                        size=size_reference or sweep.property("points"),
                                        kind="frequency",
                                        unit="Hz",
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            ),
        ],
    )


def _state_sized_collect_snapshot(points: int) -> InstrumentStateSnapshot:
    return InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.sweep/v1",
                property_id="points",
                value=StateValue(points),
            )
        ],
    )


def _state_sized_collect_command(points: int) -> CollectCommand:
    return _collect_command(
        dimensions=[
            CollectAxisRequest(
                id="channel",
                kind="channel",
                size=2,
            ),
            CollectAxisRequest(
                id="frequency",
                kind="frequency",
                size=points,
                unit="Hz",
            ),
        ]
    )


def _state_discriminated_collect_description(
    *,
    discriminator: PropertyRef | None = None,
    cases: tuple[AcquisitionCaseSpec, ...] | None = None,
    preconditions: tuple[AcquisitionPreconditionSpec, ...] = (),
) -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.state_discriminated_collect",
        implementation_version="v1",
        interfaces=[
            interface(
                "test.source/v1",
                components=[
                    component(
                        "output",
                        state=discriminated_state(
                            enum_property(
                                "mode",
                                choices=("voltage", "current"),
                            ),
                            common_properties=(bool_property("output_enabled"),),
                            cases=(
                                state_case(
                                    "voltage",
                                    properties=(float_property("voltage_level"),),
                                ),
                                state_case(
                                    "current",
                                    properties=(float_property("current_level"),),
                                ),
                            ),
                        ),
                    )
                ],
            ),
            interface(
                "test.monitor/v1",
                acquisitions=[
                    state_discriminated_acquisition(
                        "monitor",
                        discriminator=discriminator
                        or InterfaceRef("test.source/v1")
                        .component("output")
                        .property("mode"),
                        cases=cases
                        or (
                            acquisition_case(
                                "voltage",
                                results=(
                                    acquisition_result(
                                        "monitored_current",
                                        unit="A",
                                    ),
                                ),
                            ),
                            acquisition_case(
                                "current",
                                results=(
                                    acquisition_result(
                                        "monitored_voltage",
                                        unit="V",
                                    ),
                                ),
                            ),
                        ),
                        preconditions=preconditions,
                    )
                ],
            ),
        ],
    )


def _state_discriminated_collect_snapshot(
    mode: str,
    *,
    output_enabled: bool = False,
) -> InstrumentStateSnapshot:
    level_property_id = "voltage_level" if mode == "voltage" else "current_level"
    return InstrumentStateSnapshot(
        instrument_id="source-0",
        properties=[
            RecordInstrumentPropertyState(
                interface_id="test.source/v1",
                component_path=["output"],
                property_id="mode",
                value=StateValue(mode),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.source/v1",
                component_path=["output"],
                property_id="output_enabled",
                value=StateValue(output_enabled),
            ),
            RecordInstrumentPropertyState(
                interface_id="test.source/v1",
                component_path=["output"],
                property_id=level_property_id,
                value=StateValue(0.1),
            ),
        ],
    )


def _state_discriminated_collect_command(
    result_id: str,
    *,
    unit: str,
) -> CollectCommand:
    return CollectCommand(
        command_id=f"collect-{result_id}",
        instrument_id="source-0",
        point_index=0,
        point_count=1,
        requests=[
            CollectResultRequest(
                id=result_id,
                interface_id="test.monitor/v1",
                acquisition_id="monitor",
                result_id=result_id,
                unit=unit,
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
        command_id="collect-command",
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
