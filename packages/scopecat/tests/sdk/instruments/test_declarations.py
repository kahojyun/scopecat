from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, assert_type, cast

import pytest

from scopecat.kernel.instrument_members import OperationArgumentRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import Int as IntType
from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_types import String as StringType
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.program.state import DesiredState
from scopecat.program.value_refs import ValueRef
from scopecat.program.values import input as program_input
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments import (
    acquisition as expected_acquisition,
)
from scopecat.sdk.instruments import (
    acquisition_axis as expected_axis,
)
from scopecat.sdk.instruments import (
    acquisition_case as expected_acquisition_case,
)
from scopecat.sdk.instruments import (
    acquisition_precondition as expected_precondition,
)
from scopecat.sdk.instruments import (
    acquisition_result as expected_result,
)
from scopecat.sdk.instruments import (
    acquisition_results,
    bool_property,
    enum_property,
    int_property,
    quantity_property,
)
from scopecat.sdk.instruments import component as expected_component
from scopecat.sdk.instruments import (
    discriminated_state as expected_discriminated_state,
)
from scopecat.sdk.instruments import (
    interface as expected_interface,
)
from scopecat.sdk.instruments import operation as expected_operation
from scopecat.sdk.instruments import (
    operation_argument as expected_operation_argument,
)
from scopecat.sdk.instruments import state_case as expected_state_case
from scopecat.sdk.instruments import (
    state_discriminated_acquisition as expected_discriminated_acquisition,
)
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    DeclaredAcquisition,
    DeclaredObservedState,
    DeclaredOperation,
    acquisition,
    acquisition_case,
    argument,
    axis,
    compile_interface,
    component,
    declared_acquisition,
    declared_acquisition_ref,
    declared_argument_ref,
    declared_component_ref,
    declared_discriminator_ref,
    declared_interface_ref,
    declared_observed_state,
    declared_operation,
    declared_operation_ref,
    declared_property_ref,
    declared_result_ref,
    declared_state_assignments,
    declared_state_target,
    discriminated_state,
    instrument_interface,
    instrument_observed_state,
    instrument_result,
    instrument_state,
    interface_discriminator,
    member,
    operation,
    precondition,
    result,
    state_case,
    state_discriminated_acquisition,
    state_field,
)

type Desired[T] = T | ValueRef


@instrument_state
@dataclass(frozen=True, slots=True, kw_only=True)
class SweepState:
    start_frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="Start frequency",
            description="First stimulus frequency.",
        ),
    ] = None
    points: Annotated[
        Desired[int] | None,
        member(
            minimum=2,
            label="Sweep points",
            description="Number of frequency points.",
        ),
    ] = None
    trace: Annotated[
        Desired[Literal["S11", "S21"]] | None,
        member(label="Trace", description="Selected response."),
    ] = None
    output_enabled: Annotated[
        Desired[bool] | None,
        member(label="Output", description="Whether output is enabled."),
    ] = None


@instrument_result
@dataclass(frozen=True, slots=True)
class SweepResults:
    frequency: Annotated[
        list[float],
        result(
            unit="Hz",
            axes=("frequency",),
            label="Frequency",
            description="Stimulus frequencies.",
        ),
    ]
    response: Annotated[
        list[complex],
        result(
            id="s_parameter",
            unit="ratio",
            axes=("frequency",),
            label="Response",
            description="Complex response.",
        ),
    ]


@instrument_interface(
    "test.network_sweep/v1",
    state=SweepState,
    label="Network sweep",
    description="One typed declaration.",
)
class SweepContract(Protocol):
    @acquisition(
        label="Acquire sweep",
        description="Read one trace.",
        axes={
            "frequency": axis(
                size="points",
                kind="frequency",
                unit="Hz",
                label="Frequency",
                description="Stimulus axis.",
            )
        },
    )
    def sweep(self) -> SweepResults: ...


@instrument_state
@dataclass(frozen=True, slots=True)
class SourceCommonState:
    output_enabled: Annotated[
        Desired[bool] | None,
        member(label="Output", description="Whether output is enabled."),
    ] = None


@instrument_state
@dataclass(frozen=True, slots=True)
class VoltageState:
    range: Annotated[
        Desired[Quantity],
        member(
            id="voltage_range",
            unit="V",
            label="Voltage range",
            description="Selected voltage range.",
        ),
    ]
    level: Annotated[
        Desired[Quantity],
        member(
            id="voltage_level",
            unit="V",
            label="Voltage level",
            description="Selected voltage level.",
        ),
    ]
    output_enabled: Desired[bool] | None = None


@instrument_state
@dataclass(frozen=True, slots=True)
class CurrentState:
    range: Annotated[
        Desired[Quantity],
        member(
            id="current_range",
            unit="A",
            label="Current range",
            description="Selected current range.",
        ),
    ]
    level: Annotated[
        Desired[Quantity],
        member(
            id="current_level",
            unit="A",
            label="Current level",
            description="Selected current level.",
        ),
    ]
    output_enabled: Desired[bool] | None = None


@instrument_interface(
    "test.dc_source/v1",
    state=discriminated_state(
        member(
            id="mode",
            choices=("voltage", "current"),
            label="Mode",
            description="Selected source mode.",
        ),
        common=SourceCommonState,
        cases=(
            state_case(
                "voltage",
                VoltageState,
                fields=("range", "level"),
                required_on_entry=("range", "level"),
            ),
            state_case(
                "current",
                CurrentState,
                fields=("range", "level"),
                required_on_entry=("range", "level"),
            ),
        ),
    ),
    label="DC source",
)
class SourceContract(Protocol): ...


@instrument_state
@dataclass(frozen=True, slots=True)
class MonitorState:
    measurement_enabled: Annotated[
        Desired[bool] | None,
        member(label="Measurement", description="Whether measurement is enabled."),
    ] = None


@instrument_result
@dataclass(frozen=True, slots=True)
class MonitorResults:
    current: Annotated[
        float | None,
        result(
            id="monitored_current",
            unit="A",
            label="Current",
            description="Measured current.",
        ),
    ] = None
    voltage: Annotated[
        float | None,
        result(
            id="monitored_voltage",
            unit="V",
            label="Voltage",
            description="Measured voltage.",
        ),
    ] = None


@instrument_interface(
    "test.dc_monitor/v1",
    state=MonitorState,
    label="DC monitor",
)
class MonitorContract(Protocol):
    @state_discriminated_acquisition(
        interface_discriminator(SourceContract),
        label="Monitor",
        preconditions=(
            precondition(
                state_field(SourceCommonState, "output_enabled"),
                value=True,
                unavailable_reason="Source output is disabled.",
            ),
            precondition(
                state_field(MonitorState, "measurement_enabled"),
                value=True,
                unavailable_reason="Measurement is disabled.",
            ),
        ),
        cases=(
            acquisition_case("voltage", MonitorResults, fields=("current",)),
            acquisition_case("current", MonitorResults, fields=("voltage",)),
        ),
    )
    def monitor(self) -> MonitorResults: ...


@instrument_result
@dataclass(frozen=True, slots=True)
class ScalarResults:
    value: float


class SampleCapability(Protocol):
    @acquisition()
    def sample(self) -> ScalarResults: ...


@instrument_interface("test.inherited_protocol/v1")
class InheritedProtocolContract(SampleCapability, Protocol): ...


@instrument_interface("test.abstract_interface/v1")
class AbstractContract(ABC):
    @acquisition()
    @abstractmethod
    def sample(self) -> ScalarResults: ...


@instrument_observed_state
@dataclass(frozen=True, slots=True)
class ScannerObservation:
    channel: Annotated[
        int,
        member(
            id="active_channel",
            minimum=1,
            maximum=16,
            label="Active channel",
            description="Input currently selected by the scanner.",
        ),
    ]
    autoscan: Annotated[
        bool,
        member(
            label="Autoscan",
            description="Whether the scanner advances automatically.",
        ),
    ]


@instrument_observed_state
@dataclass(frozen=True, slots=True)
class NumericObservation:
    reading: Annotated[
        float,
        member(
            id="reading_value",
            minimum=0.0,
            maximum=5.0,
        ),
    ]


@instrument_interface(
    "test.numeric_observation/v1",
    observed_state=NumericObservation,
)
class NumericObservationContract(Protocol): ...


@instrument_observed_state
@dataclass(frozen=True, slots=True)
class UnrelatedObservation:
    value: int


@instrument_result
@dataclass(frozen=True, slots=True)
class TriggerSampleResults:
    value: Annotated[
        float,
        result(
            id="trigger_value",
            unit="V",
            label="Trigger value",
            description="Value sampled at the trigger input.",
        ),
    ]


class TriggerCapability(Protocol):
    @operation(
        id="reset_trigger",
        label="Reset trigger",
        description="Reset trigger state.",
    )
    def reset(
        self,
        cycles: Annotated[
            int,
            argument(
                id="wait_cycles",
                minimum=0,
                label="Wait cycles",
                description="Cycles to wait after reset.",
            ),
        ],
    ) -> None: ...

    @acquisition(
        id="sample_trigger",
        label="Sample trigger",
        description="Sample the trigger input.",
    )
    def sample(self) -> TriggerSampleResults: ...


class OutputCapability(Protocol):
    trigger: Annotated[
        TriggerCapability,
        component(
            id="trigger-input",
            label="Trigger input",
            description="External trigger endpoint.",
        ),
    ]

    @operation(id="arm_output", label="Arm output", description="Arm one output.")
    def arm(self) -> None: ...


@instrument_interface(
    "test.typed_control/v1",
    observed_state=ScannerObservation,
    label="Typed control",
    description="Operations, observations, and nested capabilities.",
)
class TypedControlContract(Protocol):
    output: Annotated[
        OutputCapability,
        component(
            id="output-a",
            label="Output A",
            description="First output endpoint.",
        ),
    ]

    @operation(
        id="select_input",
        label="Select input",
        description="Select one input and range.",
    )
    def select(
        self,
        channel: Annotated[
            int,
            argument(
                id="input",
                minimum=1,
                maximum=16,
                label="Input",
                description="Input index.",
            ),
        ],
        range: Annotated[
            Quantity,
            argument(
                unit="V",
                minimum=0.0,
                label="Range",
                description="Selected voltage range.",
            ),
        ],
        mode: Annotated[
            Literal["normal", "fast"],
            argument(label="Mode", description="Switching mode."),
        ],
    ) -> None: ...


@instrument_interface("test.operation_binding/v1")
class OperationBindingContract(Protocol):
    @operation(id="upload_program")
    def upload(
        self,
        channel: Annotated[int, argument(id="input", minimum=1)],
        /,
        level: Annotated[Desired[Quantity], argument(unit="V", minimum=0.0)],
        *,
        mode: Literal["once", "loop"] | ValueRef,
        program: Annotated[
            bytes,
            argument(
                id="waveform",
                payload_schema_id="test.waveform/v1",
                label="Waveform",
            ),
        ],
    ) -> None: ...


class OperationLowerer(Protocol):
    def __call__(
        self,
        channel: int,
        /,
        level: Desired[Quantity],
        *,
        mode: Literal["once", "loop"] | ValueRef,
        program: bytes,
    ) -> dict[OperationArgumentRef, object]: ...


def test_decorated_protocol_compiles_to_the_existing_contract_ir() -> None:
    compiled = assert_type(
        compile_interface(SweepContract),
        CompiledInterface[SweepContract],
    )
    assert_type(SweepContract, type[SweepContract])

    def check_client_type(client: SweepContract) -> None:
        assert_type(client.sweep(), SweepResults)

    typed_check: Callable[[SweepContract], None] = check_client_type
    assert typed_check is check_client_type
    assert_type(SweepState(points=11), SweepState)

    frequency_axis = expected_axis(
        "frequency",
        size=declared_property_ref(SweepState, "points"),
        kind="frequency",
        unit="Hz",
        label="Frequency",
        description="Stimulus axis.",
    )
    expected = expected_interface(
        "test.network_sweep/v1",
        label="Network sweep",
        description="One typed declaration.",
        properties=[
            quantity_property(
                "start_frequency",
                unit="Hz",
                label="Start frequency",
                description="First stimulus frequency.",
            ),
            int_property(
                "points",
                minimum=2,
                label="Sweep points",
                description="Number of frequency points.",
            ),
            enum_property(
                "trace",
                choices=("S11", "S21"),
                label="Trace",
                description="Selected response.",
            ),
            bool_property(
                "output_enabled",
                label="Output",
                description="Whether output is enabled.",
            ),
        ],
        acquisitions=[
            expected_acquisition(
                "sweep",
                label="Acquire sweep",
                description="Read one trace.",
                results=[
                    expected_result(
                        "frequency",
                        dtype="float64",
                        unit="Hz",
                        axes=[frequency_axis],
                        label="Frequency",
                        description="Stimulus frequencies.",
                    ),
                    expected_result(
                        "s_parameter",
                        dtype="complex128",
                        unit="ratio",
                        axes=[frequency_axis],
                        label="Response",
                        description="Complex response.",
                    ),
                ],
            )
        ],
    )

    assert compiled.spec == expected
    assert compiled.ref == declared_interface_ref(SweepContract)


@pytest.mark.parametrize(
    "contract",
    [InheritedProtocolContract, AbstractContract],
)
def test_protocol_inheritance_and_abstract_interfaces_preserve_members(
    contract: type[object],
) -> None:
    compiled = compile_interface(contract)

    assert [item.id for item in compiled.spec.acquisitions] == ["sample"]
    assert [item.id for item in acquisition_results(compiled.spec.acquisitions[0])] == [
        "value"
    ]


def test_declared_acquisition_preserves_fixed_result_type_and_field_mapping() -> None:
    compiled = compile_interface(SweepContract)

    declared = assert_type(
        declared_acquisition(compiled, SweepContract.sweep),
        DeclaredAcquisition[SweepResults],
    )

    assert declared.method_name == "sweep"
    assert declared.ref == declared_acquisition_ref(SweepContract, "sweep")
    assert declared.spec is compiled.spec.acquisitions[0]
    assert declared.discriminator is None
    assert [layout.case_value for layout in declared.layouts] == [None]
    assert [
        (field.python_name, field.result_id)
        for field in declared.active_result_fields()
    ] == [
        ("frequency", "frequency"),
        ("response", "s_parameter"),
    ]
    assert [field.spec.id for field in declared.result_fields] == [
        "frequency",
        "s_parameter",
    ]
    with pytest.raises(ValueError, match=r"fixed acquisition.*no result cases"):
        declared.active_result_fields("unexpected")


def test_declared_acquisition_rejects_a_method_from_another_interface() -> None:
    compiled = compile_interface(SweepContract)

    with pytest.raises(ValueError, match="does not belong to the compiled interface"):
        declared_acquisition(compiled, MonitorContract.monitor)


def test_declared_acquisition_resolves_an_inherited_protocol_method() -> None:
    compiled = compile_interface(InheritedProtocolContract)

    declared = assert_type(
        declared_acquisition(compiled, InheritedProtocolContract.sample),
        DeclaredAcquisition[ScalarResults],
    )

    assert declared.method_name == "sample"
    assert [field.python_name for field in declared.active_result_fields()] == ["value"]


def test_operations_observed_state_and_nested_components_compile_together() -> None:
    compiled = compile_interface(TypedControlContract)

    def check_client_type(client: TypedControlContract) -> None:
        assert_type(client.output, OutputCapability)
        assert_type(client.output.trigger, TriggerCapability)
        assert_type(
            client.select(1, Quantity(1, "V"), "normal"),
            None,
        )

    typed_check: Callable[[TypedControlContract], None] = check_client_type
    assert typed_check is check_client_type

    expected = expected_interface(
        "test.typed_control/v1",
        label="Typed control",
        description="Operations, observations, and nested capabilities.",
        properties=[
            int_property(
                "active_channel",
                minimum=1,
                maximum=16,
                label="Active channel",
                description="Input currently selected by the scanner.",
                access="read_only",
            ),
            bool_property(
                "autoscan",
                label="Autoscan",
                description="Whether the scanner advances automatically.",
                access="read_only",
            ),
        ],
        operations=[
            expected_operation(
                "select_input",
                label="Select input",
                description="Select one input and range.",
                arguments=[
                    expected_operation_argument(
                        "input",
                        value_type=Scalar(IntType(minimum=1, maximum=16)),
                        label="Input",
                        description="Input index.",
                    ),
                    expected_operation_argument(
                        "range",
                        value_type=Scalar(QuantityType(unit="V", minimum=0.0)),
                        label="Range",
                        description="Selected voltage range.",
                    ),
                    expected_operation_argument(
                        "mode",
                        value_type=Scalar(StringType(choices=("normal", "fast"))),
                        label="Mode",
                        description="Switching mode.",
                    ),
                ],
            )
        ],
        components=[
            expected_component(
                "output-a",
                label="Output A",
                description="First output endpoint.",
                operations=[
                    expected_operation(
                        "arm_output",
                        label="Arm output",
                        description="Arm one output.",
                    )
                ],
                components=[
                    expected_component(
                        "trigger-input",
                        label="Trigger input",
                        description="External trigger endpoint.",
                        operations=[
                            expected_operation(
                                "reset_trigger",
                                label="Reset trigger",
                                description="Reset trigger state.",
                                arguments=[
                                    expected_operation_argument(
                                        "wait_cycles",
                                        value_type=Scalar(IntType(minimum=0)),
                                        label="Wait cycles",
                                        description="Cycles to wait after reset.",
                                    )
                                ],
                            )
                        ],
                        acquisitions=[
                            expected_acquisition(
                                "sample_trigger",
                                label="Sample trigger",
                                description="Sample the trigger input.",
                                results=[
                                    expected_result(
                                        "trigger_value",
                                        unit="V",
                                        label="Trigger value",
                                        description=(
                                            "Value sampled at the trigger input."
                                        ),
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert compiled.spec == expected


def test_operation_and_component_refs_use_python_member_names() -> None:
    select = declared_operation_ref(TypedControlContract, "select")
    output = declared_component_ref(TypedControlContract, "output")

    assert select == declared_interface_ref(TypedControlContract).operation(
        "select_input"
    )
    assert declared_argument_ref(TypedControlContract, "select", "channel") == (
        select.argument("input")
    )
    assert output == declared_interface_ref(TypedControlContract).component("output-a")
    assert declared_operation_ref(
        TypedControlContract,
        "arm",
        component=("output",),
    ) == output.operation("arm_output")
    assert declared_component_ref(
        TypedControlContract,
        "output",
        "trigger",
    ).component_path == ("output-a", "trigger-input")


def test_declared_operation_preserves_signature_and_argument_layout() -> None:
    compiled = compile_interface(OperationBindingContract)

    def require_operation_lowerer(value: OperationLowerer) -> OperationLowerer:
        return value

    declared = declared_operation(compiled, OperationBindingContract.upload)
    lowerer = assert_type(
        require_operation_lowerer(declared.lower_arguments),
        OperationLowerer,
    )
    payload = b"compiled waveform"
    lowered = assert_type(
        lowerer(
            3,
            level=Quantity(0.5, "V"),
            mode="loop",
            program=payload,
        ),
        dict[OperationArgumentRef, object],
    )

    assert isinstance(declared, DeclaredOperation)
    assert declared.method_name == "upload"
    assert declared.ref == declared_operation_ref(
        OperationBindingContract,
        "upload",
    )
    assert declared.spec is compiled.spec.operations[0]
    assert [argument.python_name for argument in declared.arguments] == [
        "channel",
        "level",
        "mode",
        "program",
    ]
    assert [argument.argument_id for argument in declared.arguments] == [
        "input",
        "level",
        "mode",
        "waveform",
    ]
    assert declared.arguments[1].spec.value_type == Scalar(
        QuantityType(unit="V", minimum=0.0)
    )
    assert declared.arguments[2].spec.value_type == Scalar(
        StringType(choices=("once", "loop"))
    )
    assert all(
        argument.spec is spec
        for argument, spec in zip(
            declared.arguments,
            compiled.spec.operations[0].arguments,
            strict=True,
        )
    )
    assert list(lowered) == [argument.ref for argument in declared.arguments]
    assert list(lowered.values()) == [
        3,
        Quantity(0.5, "V"),
        "loop",
        payload,
    ]
    payload_argument = declared.arguments[-1]
    assert payload_argument.spec.value_type == Scalar(
        PayloadType(schema_id="test.waveform/v1")
    )
    assert lowered[payload_argument.ref] is payload

    symbolic_level = program_input("level", Scalar(QuantityType(unit="V")))
    symbolic_lowered = assert_type(
        declared.lower_arguments(
            3,
            level=symbolic_level,
            mode="once",
            program=payload,
        ),
        dict[OperationArgumentRef, object],
    )
    assert symbolic_lowered[declared.arguments[1].ref] is symbolic_level


def test_declared_operation_uses_signature_bind_errors() -> None:
    declared = declared_operation(
        compile_interface(OperationBindingContract),
        OperationBindingContract.upload,
    )
    lower = cast("Callable[..., object]", declared.lower_arguments)

    with pytest.raises(TypeError, match="missing a required argument: 'program'"):
        lower(3, Quantity(0.5, "V"), mode="once")
    with pytest.raises(TypeError, match="positional-only"):
        lower(
            channel=3,
            level=Quantity(0.5, "V"),
            mode="once",
            program=b"waveform",
        )
    with pytest.raises(TypeError, match="too many positional arguments"):
        lower(3, Quantity(0.5, "V"), "once", b"waveform")
    with pytest.raises(TypeError, match="unexpected keyword argument 'extra'"):
        lower(
            3,
            Quantity(0.5, "V"),
            mode="once",
            program=b"waveform",
            extra=True,
        )


def test_declared_operation_resolves_nested_component_arguments() -> None:
    compiled = compile_interface(TypedControlContract)
    component_path = ("output", "trigger")

    declared = declared_operation(
        compiled,
        TriggerCapability.reset,
        component=component_path,
    )
    [argument] = declared.arguments

    assert declared.ref == declared_operation_ref(
        TypedControlContract,
        "reset",
        component=component_path,
    )
    assert declared.spec is compiled.spec.components[0].components[0].operations[0]
    assert argument.ref == declared_argument_ref(
        TypedControlContract,
        "reset",
        "cycles",
        component=component_path,
    )
    assert assert_type(
        declared.lower_arguments(cycles=2),
        dict[OperationArgumentRef, object],
    ) == {argument.ref: 2}


def test_declared_operation_rejects_a_method_from_another_interface() -> None:
    compiled = compile_interface(TypedControlContract)

    with pytest.raises(ValueError, match="does not belong to the compiled interface"):
        declared_operation(compiled, OperationBindingContract.upload)


def test_operation_symbolic_values_do_not_make_none_a_valid_argument() -> None:
    @instrument_interface("test.invalid_optional_operation/v1")
    class InvalidOptionalOperation(Protocol):
        @operation()
        def invoke(self, value: int | ValueRef | None) -> None: ...

    with pytest.raises(TypeError, match="unsupported operation argument union"):
        compile_interface(InvalidOptionalOperation)


def test_nested_component_member_refs_use_python_paths() -> None:
    component_path = ("output", "trigger")
    trigger = declared_component_ref(TypedControlContract, *component_path)
    reset = declared_operation_ref(
        TypedControlContract,
        "reset",
        component=component_path,
    )
    sample = declared_acquisition_ref(
        TypedControlContract,
        "sample",
        component=component_path,
    )

    assert reset == trigger.operation("reset_trigger")
    assert declared_argument_ref(
        TypedControlContract,
        "reset",
        "cycles",
        component=component_path,
    ) == reset.argument("wait_cycles")
    assert sample == trigger.acquisition("sample_trigger")
    assert declared_result_ref(
        TypedControlContract,
        "sample",
        "value",
        component=component_path,
    ) == sample.result("trigger_value")


def test_declared_acquisition_resolves_nested_component_result_layout() -> None:
    compiled = compile_interface(TypedControlContract)
    component_path = ("output", "trigger")

    declared = assert_type(
        declared_acquisition(
            compiled,
            TriggerCapability.sample,
            component=component_path,
        ),
        DeclaredAcquisition[TriggerSampleResults],
    )

    trigger_spec = compiled.spec.components[0].components[0]
    assert declared.method_name == "sample"
    assert declared.ref == declared_acquisition_ref(
        TypedControlContract,
        "sample",
        component=component_path,
    )
    assert declared.spec is trigger_spec.acquisitions[0]
    assert declared.discriminator is None
    assert [layout.case_value for layout in declared.layouts] == [None]
    assert [
        (field.python_name, field.result_id, field.spec.id)
        for field in declared.active_result_fields()
    ] == [
        (
            "value",
            "trigger_value",
            "trigger_value",
        )
    ]


def test_observed_state_has_refs_but_cannot_be_encoded_as_desired_state() -> None:
    observation = ScannerObservation(channel=3, autoscan=True)

    assert declared_property_ref(ScannerObservation, "channel") == (
        declared_interface_ref(TypedControlContract).property("active_channel")
    )
    with pytest.raises(TypeError, match="instrument state is missing its decorator"):
        declared_state_assignments(observation)


def test_declared_observed_state_preserves_type_order_and_compiled_identity() -> None:
    compiled = compile_interface(TypedControlContract)

    declared = assert_type(
        declared_observed_state(compiled, ScannerObservation),
        DeclaredObservedState[ScannerObservation],
    )

    assert declared.state_type is ScannerObservation
    assert [(field.python_name, field.property_id) for field in declared.fields] == [
        ("channel", "active_channel"),
        ("autoscan", "autoscan"),
    ]
    assert [field.ref for field in declared.fields] == [
        declared_property_ref(ScannerObservation, "channel"),
        declared_property_ref(ScannerObservation, "autoscan"),
    ]
    assert all(
        field.spec is spec
        for field, spec in zip(
            declared.fields,
            compiled.spec.properties,
            strict=True,
        )
    )
    assert declared.fields[0].spec.value_type == Scalar(IntType(minimum=1, maximum=16))


def test_declared_observed_state_decodes_exact_refs_and_ignores_extras() -> None:
    declared = declared_observed_state(
        compile_interface(TypedControlContract),
        ScannerObservation,
    )
    channel, autoscan = (field.ref for field in declared.fields)
    snapshot = InstrumentStateSnapshot(
        instrument_id="scanner-0",
        properties=[
            InstrumentPropertyState(
                interface_id=channel.interface_id,
                component_path=list(channel.component_path),
                property_id=channel.property_id,
                value=StateValue(3),
            ),
            InstrumentPropertyState(
                interface_id=autoscan.interface_id,
                component_path=list(autoscan.component_path),
                property_id=autoscan.property_id,
                value=StateValue(True),
            ),
            InstrumentPropertyState(
                interface_id=channel.interface_id,
                component_path=["unrelated-component"],
                property_id=channel.property_id,
                value=StateValue(15),
            ),
            InstrumentPropertyState(
                interface_id="test.unrelated_observation/v1",
                property_id=channel.property_id,
                value=StateValue(16),
            ),
        ],
    )

    assert assert_type(
        declared.decode(snapshot),
        ScannerObservation,
    ) == ScannerObservation(channel=3, autoscan=True)


def test_declared_observed_state_reports_missing_python_and_wire_fields() -> None:
    declared = declared_observed_state(
        compile_interface(TypedControlContract),
        ScannerObservation,
    )

    with pytest.raises(
        ValueError,
        match="observed-state snapshot is missing declared fields",
    ) as captured:
        declared.decode(InstrumentStateSnapshot(instrument_id="scanner-0"))

    message = str(captured.value)
    assert "observed-state snapshot is missing declared fields" in message
    for field in declared.fields:
        assert field.python_name in message
        assert repr(field.ref) in message


def test_declared_observed_state_coerces_values_and_reports_field_path() -> None:
    declared = declared_observed_state(
        compile_interface(NumericObservationContract),
        NumericObservation,
    )
    [field] = declared.fields

    decoded = declared.decode(
        InstrumentStateSnapshot(
            instrument_id="meter-0",
            properties=[
                InstrumentPropertyState(
                    interface_id=field.ref.interface_id,
                    component_path=list(field.ref.component_path),
                    property_id=field.ref.property_id,
                    value=StateValue(1),
                )
            ],
        )
    )
    assert decoded == NumericObservation(reading=1.0)
    assert type(decoded.reading) is float

    with pytest.raises(
        ValueValidationError,
        match=r"observed_state\.reading: expected float, got 'invalid'",
    ):
        declared.decode(
            InstrumentStateSnapshot(
                instrument_id="meter-0",
                properties=[
                    InstrumentPropertyState(
                        interface_id=field.ref.interface_id,
                        component_path=list(field.ref.component_path),
                        property_id=field.ref.property_id,
                        value=StateValue("invalid"),
                    )
                ],
            )
        )


def test_declared_observed_state_requires_the_interface_exact_state_type() -> None:
    compiled = compile_interface(TypedControlContract)

    with pytest.raises(
        ValueError,
        match=("declares observed state ScannerObservation, not UnrelatedObservation"),
    ):
        declared_observed_state(compiled, UnrelatedObservation)

    with pytest.raises(
        ValueError,
        match="compiled interface does not declare observed state",
    ):
        declared_observed_state(compile_interface(SweepContract), ScannerObservation)


def test_declaration_ref_helpers_use_python_member_names() -> None:
    acquisition_ref = declared_acquisition_ref(SweepContract, "sweep")

    assert declared_property_ref(SweepState, "start_frequency") == (
        declared_interface_ref(SweepContract).property("start_frequency")
    )
    assert acquisition_ref.acquisition_id == "sweep"
    assert declared_result_ref(SweepContract, "sweep", "response") == (
        acquisition_ref.result("s_parameter")
    )


def test_discriminated_state_compiles_and_encodes_implicit_mode() -> None:
    compiled = compile_interface(SourceContract)
    expected = expected_interface(
        "test.dc_source/v1",
        label="DC source",
        state=expected_discriminated_state(
            enum_property(
                "mode",
                choices=("voltage", "current"),
                label="Mode",
                description="Selected source mode.",
            ),
            common_properties=(
                bool_property(
                    "output_enabled",
                    label="Output",
                    description="Whether output is enabled.",
                ),
            ),
            cases=(
                expected_state_case(
                    "voltage",
                    properties=(
                        quantity_property(
                            "voltage_range",
                            unit="V",
                            label="Voltage range",
                            description="Selected voltage range.",
                        ),
                        quantity_property(
                            "voltage_level",
                            unit="V",
                            label="Voltage level",
                            description="Selected voltage level.",
                        ),
                    ),
                    required_on_entry_property_ids=(
                        "voltage_range",
                        "voltage_level",
                    ),
                ),
                expected_state_case(
                    "current",
                    properties=(
                        quantity_property(
                            "current_range",
                            unit="A",
                            label="Current range",
                            description="Selected current range.",
                        ),
                        quantity_property(
                            "current_level",
                            unit="A",
                            label="Current level",
                            description="Selected current level.",
                        ),
                    ),
                    required_on_entry_property_ids=(
                        "current_range",
                        "current_level",
                    ),
                ),
            ),
        ),
    )
    assert compiled.spec == expected

    voltage = VoltageState(
        range=Quantity(1, "V"),
        level=Quantity(0.1, "V"),
        output_enabled=True,
    )
    assert declared_state_assignments(voltage) == {
        declared_discriminator_ref(SourceContract): "voltage",
        declared_property_ref(VoltageState, "range"): Quantity(1, "V"),
        declared_property_ref(VoltageState, "level"): Quantity(0.1, "V"),
        declared_property_ref(SourceCommonState, "output_enabled"): True,
    }


def test_state_discriminated_acquisition_supports_cross_interface_members() -> None:
    compiled = compile_interface(MonitorContract)
    source_output = declared_property_ref(SourceCommonState, "output_enabled")
    measurement_enabled = declared_property_ref(
        MonitorState,
        "measurement_enabled",
    )
    expected = expected_interface(
        "test.dc_monitor/v1",
        label="DC monitor",
        properties=[
            bool_property(
                "measurement_enabled",
                label="Measurement",
                description="Whether measurement is enabled.",
            )
        ],
        acquisitions=[
            expected_discriminated_acquisition(
                "monitor",
                label="Monitor",
                discriminator=declared_discriminator_ref(SourceContract),
                preconditions=(
                    expected_precondition(
                        source_output,
                        value=True,
                        unavailable_reason="Source output is disabled.",
                    ),
                    expected_precondition(
                        measurement_enabled,
                        value=True,
                        unavailable_reason="Measurement is disabled.",
                    ),
                ),
                cases=(
                    expected_acquisition_case(
                        "voltage",
                        results=(
                            expected_result(
                                "monitored_current",
                                unit="A",
                                label="Current",
                                description="Measured current.",
                            ),
                        ),
                    ),
                    expected_acquisition_case(
                        "current",
                        results=(
                            expected_result(
                                "monitored_voltage",
                                unit="V",
                                label="Voltage",
                                description="Measured voltage.",
                            ),
                        ),
                    ),
                ),
            )
        ],
    )

    assert compiled.spec == expected
    monitor = declared_acquisition_ref(MonitorContract, "monitor")
    assert declared_result_ref(MonitorContract, "monitor", "current") == (
        monitor.result("monitored_current")
    )
    assert declared_result_ref(MonitorContract, "monitor", "voltage") == (
        monitor.result("monitored_voltage")
    )

    declared = assert_type(
        declared_acquisition(compiled, MonitorContract.monitor),
        DeclaredAcquisition[MonitorResults],
    )
    assert declared.discriminator == declared_discriminator_ref(SourceContract)
    assert [layout.case_value for layout in declared.layouts] == [
        "voltage",
        "current",
    ]
    assert [
        (field.python_name, field.result_id)
        for field in declared.active_result_fields("voltage")
    ] == [("current", "monitored_current")]
    assert [
        (field.python_name, field.result_id)
        for field in declared.active_result_fields("current")
    ] == [("voltage", "monitored_voltage")]
    with pytest.raises(ValueError, match="requires a concrete discriminator case"):
        declared.active_result_fields()
    with pytest.raises(ValueError, match="has no result case 'resistance'"):
        declared.active_result_fields("resistance")


def test_declared_state_codec_omits_none_without_injecting_methods() -> None:
    state = SweepState(points=11, trace="S21")

    assert not hasattr(state, "target_assignments")
    assert declared_state_assignments(state) == {
        declared_property_ref(SweepState, "points"): 11,
        declared_property_ref(SweepState, "trace"): "S21",
    }
    target: DesiredState = declared_state_target(state)
    assert target.target_assignments() == declared_state_assignments(state)


def test_compilation_and_fresh_spec_do_not_share_mutable_models() -> None:
    first = compile_interface(SweepContract)
    second = compile_interface(SweepContract)

    assert first.spec is not second.spec
    first.spec.properties[0].label = "changed"
    assert second.spec.properties[0].label == "Start frequency"
    assert first.fresh_spec() is not first.spec


def test_fixed_acquisition_rejects_runtime_arguments() -> None:
    @instrument_interface("test.invalid_acquisition/v1")
    class InvalidAcquisition(Protocol):
        @acquisition()
        def sample(self, channel: int) -> SweepResults: ...

    with pytest.raises(TypeError, match="must accept only self"):
        compile_interface(InvalidAcquisition)


def test_acquisition_case_rejects_an_unknown_selected_result_field() -> None:
    @instrument_interface("test.invalid_result_selection/v1")
    class InvalidAcquisition(Protocol):
        @state_discriminated_acquisition(
            interface_discriminator(SourceContract),
            cases=(
                acquisition_case(
                    "voltage",
                    MonitorResults,
                    fields=("missing",),
                ),
                acquisition_case(
                    "current",
                    MonitorResults,
                    fields=("voltage",),
                ),
            ),
        )
        def monitor(self) -> MonitorResults: ...

    with pytest.raises(ValueError, match=r"references unknown fields: \['missing'\]"):
        compile_interface(InvalidAcquisition)
