from __future__ import annotations

import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import Annotated, Literal, Protocol, assert_type, cast

import pytest

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Int as IntType
from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_types import String as StringType
from scopecat.program.state import DesiredState
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments import (
    FixedAcquisitionSpec,
    acquisition_results,
    bool_property,
    enum_property,
    int_property,
    quantity_property,
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
    DeclaredInterfaceLayout,
    DeclaredOperation,
    DeclaredStateLayout,
    StateProjectionField,
    StateProjectionLayout,
    acquisition,
    acquisition_case,
    argument,
    axis,
    compile_interface,
    declared_acquisition,
    declared_acquisition_ref,
    declared_argument_ref,
    declared_discriminator_ref,
    declared_interface_layout,
    declared_interface_ref,
    declared_operation,
    declared_operation_ref,
    declared_property_ref,
    declared_result_ref,
    discriminated_state,
    instrument_interface,
    instrument_result,
    instrument_state,
    instrument_state_projection,
    interface_discriminator,
    member,
    member_field,
    operation,
    precondition,
    result,
    result_field,
    state_case,
    state_discriminated_acquisition,
    state_field,
    state_projection_assignments,
    state_projection_field,
    state_projection_target,
    target_from_state_projection_assignments,
)

type ConcreteAlias[ValueT] = ValueT
type ModeAlias = Literal["once", "loop"]


@instrument_result
class AliasedScalarResults:
    value: ConcreteAlias[float] = result_field()


@instrument_result
class GenericScalarResults[ValueT]:
    value: ValueT = result_field()


@instrument_result
class OptionalScalarResults:
    value: Annotated[float | None, result(unit="V")]


@instrument_result
class TypingOptionalScalarResults:
    value: typing.Optional[float]  # pyright: ignore[reportDeprecated]  # noqa: UP045


@instrument_interface("test.invalid_parameterized_result/v1")
class ParameterizedGenericResultContract(Protocol):
    @acquisition()
    def sample(self) -> GenericScalarResults[float]: ...


@instrument_interface("test.invalid_optional_result/v1")
class OptionalResultContract(Protocol):
    @acquisition()
    def sample(self) -> OptionalScalarResults: ...


@instrument_interface("test.invalid_typing_optional_result/v1")
class TypingOptionalResultContract(Protocol):
    @acquisition()
    def sample(self) -> TypingOptionalScalarResults: ...


@instrument_state
class SweepState:
    start_frequency: Quantity = member_field(
        unit="Hz",
        label="Start frequency",
        description="First stimulus frequency.",
    )
    points: int = member_field(
        minimum=2,
        label="Sweep points",
        description="Number of frequency points.",
    )
    trace: Literal["S11", "S21"] = member_field(
        label="Trace",
        description="Selected response.",
    )
    output_enabled: bool = member_field(
        label="Output",
        description="Whether output is enabled.",
    )


@instrument_result
class SweepResults:
    frequency: list[float] = result_field(
        unit="Hz",
        axes=("frequency",),
        label="Frequency",
        description="Stimulus frequencies.",
    )
    response: list[complex] = result_field(
        id="s_parameter",
        unit="ratio",
        axes=("frequency",),
        label="Response",
        description="Complex response.",
    )


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
class SourceCommonState:
    output_enabled: bool = member_field(
        label="Output",
        description="Whether output is enabled.",
    )


@instrument_state
class VoltageState(SourceCommonState):
    range: Quantity = member_field(
        id="voltage_range",
        unit="V",
        label="Voltage range",
        description="Selected voltage range.",
    )
    level: Quantity = member_field(
        id="voltage_level",
        unit="V",
        label="Voltage level",
        description="Selected voltage level.",
    )


@instrument_state
class CurrentState(SourceCommonState):
    range: Quantity = member_field(
        id="current_range",
        unit="A",
        label="Current range",
        description="Selected current range.",
    )
    level: Quantity = member_field(
        id="current_level",
        unit="A",
        label="Current level",
        description="Selected current level.",
    )


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
                required_on_entry=("range", "level"),
            ),
            state_case(
                "current",
                CurrentState,
                required_on_entry=("range", "level"),
            ),
        ),
    ),
    label="DC source",
)
class SourceContract(Protocol): ...


@instrument_state
class MonitorState:
    measurement_enabled: bool = member_field(
        label="Measurement",
        description="Whether measurement is enabled.",
    )


@instrument_result
class MonitorResults:
    current: float = result_field(
        id="monitored_current",
        unit="A",
        label="Current",
        description="Measured current.",
    )
    voltage: float = result_field(
        id="monitored_voltage",
        unit="V",
        label="Voltage",
        description="Measured voltage.",
    )


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
                state_field(SourceContract, SourceCommonState, "output_enabled"),
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


@instrument_state
class ScannerState:
    channel: int = member_field(
        id="active_channel",
        access="read_only",
        minimum=1,
        maximum=16,
        label="Active channel",
        description="Input currently selected by the scanner.",
    )
    autoscan: bool = member_field(
        access="read_only",
        label="Autoscan",
        description="Whether the scanner advances automatically.",
    )


@instrument_state
class NumericState:
    reading: Annotated[
        float,
        member(
            id="reading_value",
            access="read_only",
            minimum=0.0,
            maximum=5.0,
        ),
    ]


@instrument_interface(
    "test.numeric_state/v1",
    state=NumericState,
)
class NumericStateContract(Protocol): ...


@instrument_interface(
    "test.typed_control/v1",
    state=ScannerState,
    label="Typed control",
    description="Operations and state readback.",
)
class TypedControlContract(Protocol):
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
        level: Annotated[Quantity, argument(unit="V", minimum=0.0)],
        *,
        mode: Literal["once", "loop"],
        program: Annotated[
            bytes,
            argument(
                id="waveform",
                payload_schema_id="test.waveform/v1",
                label="Waveform",
            ),
        ],
    ) -> None: ...


def test_declaration_decorators_build_typed_python_dataclasses() -> None:
    state = assert_type(
        SweepState(
            start_frequency=Quantity(1.0, "GHz"),
            points=11,
            trace="S11",
            output_enabled=False,
        ),
        SweepState,
    )
    results = assert_type(
        SweepResults(frequency=[1.0], response=[1.0 + 0.0j]),
        SweepResults,
    )

    assert is_dataclass(SweepState)
    assert is_dataclass(SweepResults)
    assert tuple(item.name for item in fields(SweepState)) == (
        "start_frequency",
        "points",
        "trace",
        "output_enabled",
    )
    assert not hasattr(state, "__dict__")
    assert not hasattr(results, "__dict__")
    with pytest.raises(FrozenInstanceError):
        state.__setattr__("points", 12)

    positional_constructor = cast("Callable[[int], SweepState]", SweepState)
    with pytest.raises(TypeError):
        positional_constructor(11)

    voltage = assert_type(
        VoltageState(
            output_enabled=False,
            range=Quantity(1.0, "V"),
            level=Quantity(0.1, "V"),
        ),
        VoltageState,
    )
    assert isinstance(voltage, SourceCommonState)
    assert tuple(item.name for item in fields(VoltageState)) == (
        "output_enabled",
        "range",
        "level",
    )
    assert not hasattr(voltage, "__dict__")
    incomplete_voltage = cast("Callable[..., VoltageState]", VoltageState)
    with pytest.raises(TypeError, match="output_enabled"):
        incomplete_voltage(
            range=Quantity(1.0, "V"),
            level=Quantity(0.1, "V"),
        )


def test_field_specifiers_support_factories_and_override_annotated_metadata() -> None:
    @instrument_result
    class BufferedResults:
        values: list[float] = result_field(default_factory=list)

    first = assert_type(BufferedResults(), BufferedResults)
    second = BufferedResults()
    assert first.values == []
    assert first.values is not second.values

    @instrument_state
    class PriorityState:
        value: Annotated[int, member(id="annotated", minimum=1)] = member_field(
            id="native",
            minimum=2,
        )

    @instrument_interface("test.field_metadata_priority/v1", state=PriorityState)
    class PriorityContract(Protocol): ...

    compiled = compile_interface(PriorityContract)
    assert compiled.spec.properties == [int_property("native", minimum=2)]


def test_ordinary_interface_metadata_inheritance_is_preserved() -> None:
    class DerivedSource(SourceContract, Protocol): ...

    assert declared_interface_ref(DerivedSource) == declared_interface_ref(
        SourceContract
    )
    assert declared_discriminator_ref(DerivedSource) == declared_discriminator_ref(
        SourceContract
    )
    assert (
        compile_interface(DerivedSource).spec == compile_interface(SourceContract).spec
    )


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
    assert_type(
        SweepState(
            start_frequency=Quantity(1.0, "GHz"),
            points=11,
            trace="S11",
            output_enabled=False,
        ),
        SweepState,
    )

    frequency_axis = expected_axis(
        "frequency",
        size=declared_property_ref(SweepContract, SweepState, "points"),
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


def test_operations_and_read_only_state_compile_together() -> None:
    compiled = compile_interface(TypedControlContract)

    def check_client_type(client: TypedControlContract) -> None:
        assert_type(
            client.select(1, Quantity(1, "V"), "normal"),
            None,
        )

    typed_check: Callable[[TypedControlContract], None] = check_client_type
    assert typed_check is check_client_type

    expected = expected_interface(
        "test.typed_control/v1",
        label="Typed control",
        description="Operations and state readback.",
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
    )

    assert compiled.spec == expected
    assert not compiled.spec.components


def test_declared_interface_layout_preserves_root_members_and_spec_identity() -> None:
    compiled = compile_interface(TypedControlContract)

    layout = assert_type(
        declared_interface_layout(compiled),
        DeclaredInterfaceLayout[TypedControlContract],
    )

    assert layout.compiled is compiled
    [state] = layout.states
    assert state.source_type is ScannerState
    assert [field.python_name for field in state.fields] == [
        "channel",
        "autoscan",
    ]
    assert all(
        field.spec is spec
        for field, spec in zip(
            state.fields,
            compiled.spec.properties,
            strict=True,
        )
    )
    assert all(field.spec.access == "read_only" for field in state.fields)

    root = layout.root
    assert root.capability_type is TypedControlContract
    assert root.ref is compiled.ref
    assert root.spec is compiled.spec
    [select] = root.operations
    assert select.method_name == "select"
    assert select.ref.operation_id == "select_input"
    assert select.spec is compiled.spec.operations[0]
    assert [argument.python_name for argument in select.arguments] == [
        "channel",
        "range",
        "mode",
    ]
    assert [argument.argument_id for argument in select.arguments] == [
        "input",
        "range",
        "mode",
    ]
    assert all(
        argument.spec is spec
        for argument, spec in zip(
            select.arguments,
            select.spec.arguments,
            strict=True,
        )
    )
    assert [argument.annotation for argument in select.arguments] == [
        int,
        Quantity,
        Literal["normal", "fast"],
    ]
    assert root.acquisitions == ()


def test_declared_interface_layout_covers_inherited_and_state_declarations() -> None:
    inherited = declared_interface_layout(compile_interface(InheritedProtocolContract))
    [sample] = inherited.root.acquisitions

    assert sample.method_name == "sample"
    assert sample.spec is inherited.compiled.spec.acquisitions[0]
    assert sample.layouts[0].result_type is ScalarResults

    flat = declared_interface_layout(compile_interface(SweepContract))
    discriminated = declared_interface_layout(compile_interface(SourceContract))
    monitor = declared_interface_layout(compile_interface(MonitorContract))

    assert [state.source_type for state in flat.states] == [SweepState]
    [flat_state] = flat.states
    assert [field.python_name for field in flat_state.fields] == [
        "start_frequency",
        "points",
        "trace",
        "output_enabled",
    ]
    assert [field.annotation for field in flat_state.fields] == [
        Quantity,
        int,
        Literal["S11", "S21"],
        bool,
    ]
    assert flat_state.required_fields == ()
    assert flat_state.constants == ()
    assert flat_state.role == "flat"
    assert flat_state.projection_stem == "Sweep"

    assert [state.source_type for state in discriminated.states] == [
        SourceCommonState,
        VoltageState,
        CurrentState,
    ]
    common, voltage, current = discriminated.states
    assert [field.python_name for field in common.fields] == ["output_enabled"]
    assert common.role == "common"
    assert common.projection_stem == "SourceContract"
    assert [field.python_name for field in voltage.fields] == [
        "output_enabled",
        "range",
        "level",
    ]
    assert voltage.role == "case"
    assert voltage.projection_stem == "Voltage"
    assert voltage.required_fields == ("range", "level")
    assert voltage.constants == (
        (declared_discriminator_ref(SourceContract), "voltage"),
    )
    assert [field.python_name for field in current.fields] == [
        "output_enabled",
        "range",
        "level",
    ]
    assert current.role == "case"
    assert current.projection_stem == "Current"
    assert current.required_fields == ("range", "level")
    assert current.constants == (
        (declared_discriminator_ref(SourceContract), "current"),
    )

    assert [state.source_type for state in monitor.states] == [MonitorState]
    assert monitor.states[0].role == "flat"
    assert monitor.states[0].projection_stem == "Monitor"
    [monitor_acquisition] = monitor.root.acquisitions
    assert [item.result_type for item in monitor_acquisition.layouts] == [
        MonitorResults,
        MonitorResults,
    ]


def test_operation_refs_use_python_member_names() -> None:
    select = declared_operation_ref(TypedControlContract, "select")

    assert select == declared_interface_ref(TypedControlContract).operation(
        "select_input"
    )
    assert declared_argument_ref(TypedControlContract, "select", "channel") == (
        select.argument("input")
    )


def test_declared_operation_preserves_argument_layout() -> None:
    compiled = compile_interface(OperationBindingContract)

    declared = declared_operation(compiled, OperationBindingContract.upload)

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
    assert [argument.annotation for argument in declared.arguments] == [
        int,
        Quantity,
        Literal["once", "loop"],
        bytes,
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
    payload_argument = declared.arguments[-1]
    assert payload_argument.spec.value_type == Scalar(
        PayloadType(schema_id="test.waveform/v1")
    )


def test_declared_operation_rejects_a_method_from_another_interface() -> None:
    compiled = compile_interface(TypedControlContract)

    with pytest.raises(ValueError, match="does not belong to the compiled interface"):
        declared_operation(compiled, OperationBindingContract.upload)


def test_operation_declarations_reject_symbolic_and_optional_wrappers() -> None:
    @instrument_interface("test.invalid_optional_operation/v1")
    class InvalidOptionalOperation(Protocol):
        @operation()
        def invoke(self, value: int | ValueRef | None) -> None: ...

    with pytest.raises(TypeError, match="uses unsupported annotation"):
        compile_interface(InvalidOptionalOperation)


def test_state_declarations_reject_symbolic_and_optional_wrappers() -> None:
    @instrument_state
    class InvalidState:
        value: int | ValueRef | None = member_field()

    @instrument_interface("test.invalid_wrapped_state/v1", state=InvalidState)
    class InvalidWrappedState(Protocol): ...

    with pytest.raises(TypeError, match="uses unsupported annotation"):
        compile_interface(InvalidWrappedState)


def test_acquisition_rejects_parameterized_generic_result_types() -> None:
    with pytest.raises(
        TypeError,
        match="cannot return a parameterized instrument result",
    ):
        compile_interface(ParameterizedGenericResultContract)


def test_acquisition_rejects_bare_generic_result_classes() -> None:
    @instrument_interface("test.invalid_generic_result/v1")
    class InvalidGenericResult(Protocol):
        @state_discriminated_acquisition(
            interface_discriminator(SourceContract),
            cases=(acquisition_case("voltage", GenericScalarResults),),
        )
        def sample(self) -> ScalarResults: ...

    with pytest.raises(TypeError, match=r"instrument result .* must not be generic"):
        compile_interface(InvalidGenericResult)


def test_acquisition_rejects_optional_result_fields() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "result field 'value' cannot be optional; a successful acquisition "
            "must provide every declared result"
        ),
    ):
        compile_interface(OptionalResultContract)

    with pytest.raises(
        TypeError,
        match="result field 'value' cannot be optional",
    ):
        compile_interface(TypingOptionalResultContract)


def test_discriminated_cases_must_inherit_their_common_state() -> None:
    @instrument_state
    class CommonState:
        enabled: bool = member_field()

    @instrument_state
    class IndependentCase:
        level: int = member_field()

    @instrument_interface(
        "test.invalid_discriminated_inheritance/v1",
        state=discriminated_state(
            member(id="mode", choices=("active",)),
            common=CommonState,
            cases=(state_case("active", IndependentCase),),
        ),
    )
    class InvalidDiscriminatedInheritance(Protocol): ...

    with pytest.raises(TypeError, match="must inherit CommonState"):
        compile_interface(InvalidDiscriminatedInheritance)


def test_state_case_entry_requirements_are_case_owned() -> None:
    @instrument_state
    class CommonState:
        enabled: bool = member_field()

    @instrument_state
    class ActiveState(CommonState):
        level: int = member_field()

    @instrument_interface(
        "test.invalid_inherited_entry_requirement/v1",
        state=discriminated_state(
            member(id="mode", choices=("active",)),
            common=CommonState,
            cases=(
                state_case(
                    "active",
                    ActiveState,
                    required_on_entry=("enabled",),
                ),
            ),
        ),
    )
    class InvalidInheritedEntryRequirement(Protocol): ...

    with pytest.raises(
        ValueError,
        match=r"entry requirements reference unknown fields: \['enabled'\]",
    ):
        compile_interface(InvalidInheritedEntryRequirement)


def test_concrete_type_aliases_compile_without_authoring_wrapper_semantics() -> None:
    @instrument_state
    class AliasedState:
        count: ConcreteAlias[int] = member_field(minimum=1)
        mode: ModeAlias = member_field()

    @instrument_interface("test.concrete_alias/v1", state=AliasedState)
    class AliasedInterface(Protocol):
        @operation()
        def set_level(
            self,
            level: Annotated[
                ConcreteAlias[Quantity],
                argument(unit="V"),
            ],
        ) -> None: ...

        @acquisition()
        def sample(self) -> AliasedScalarResults: ...

    compiled = compile_interface(AliasedInterface)

    count_type = compiled.spec.properties[0].value_type.atom
    assert isinstance(count_type, IntType)
    assert count_type.minimum == 1
    assert compiled.spec.properties[1].value_type == Scalar(
        StringType(choices=("once", "loop"))
    )
    assert compiled.spec.operations[0].arguments[0].value_type == Scalar(
        QuantityType(unit="V")
    )
    acquisition_spec = compiled.spec.acquisitions[0]
    assert isinstance(acquisition_spec, FixedAcquisitionSpec)
    assert acquisition_spec.results[0].dtype == "float64"


def test_read_only_state_uses_explicit_interface_refs() -> None:
    state = ScannerState(channel=3, autoscan=True)

    assert declared_property_ref(TypedControlContract, ScannerState, "channel") == (
        declared_interface_ref(TypedControlContract).property("active_channel")
    )
    with pytest.raises(
        TypeError,
        match="instrument state projection is missing its decorator",
    ):
        state_projection_assignments(state)


def test_state_schema_can_be_reused_without_interface_ownership() -> None:
    @instrument_interface("test.reused_scanner_state/v1", state=ScannerState)
    class ReusedScannerContract(Protocol): ...

    first = compile_interface(TypedControlContract)
    second = compile_interface(ReusedScannerContract)

    assert first.spec.properties == second.spec.properties
    assert declared_property_ref(TypedControlContract, ScannerState, "channel") != (
        declared_property_ref(ReusedScannerContract, ScannerState, "channel")
    )


def test_declaration_ref_helpers_use_python_member_names() -> None:
    acquisition_ref = declared_acquisition_ref(SweepContract, "sweep")

    assert declared_property_ref(SweepContract, SweepState, "start_frequency") == (
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


def test_state_discriminated_acquisition_supports_cross_interface_members() -> None:
    compiled = compile_interface(MonitorContract)
    source_output = declared_property_ref(
        SourceContract,
        SourceCommonState,
        "output_enabled",
    )
    measurement_enabled = declared_property_ref(
        MonitorContract,
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


def test_generated_state_projection_distinguishes_omission_from_falsy_values() -> None:
    [layout] = declared_interface_layout(compile_interface(SweepContract)).states
    assert_type(layout, DeclaredStateLayout)

    @instrument_state_projection(layout)
    class SweepProjection:
        start_frequency: Quantity = state_projection_field()
        points: int = state_projection_field()
        trace: Literal["S11", "S21"] = state_projection_field()
        output_enabled: bool = state_projection_field()

    projection = SweepProjection(points=0, output_enabled=False)

    assert not hasattr(projection, "target_assignments")
    assert state_projection_assignments(projection) == {
        declared_property_ref(SweepContract, SweepState, "points"): 0,
        declared_property_ref(
            SweepContract,
            SweepState,
            "output_enabled",
        ): False,
    }
    assert repr(projection) == (
        f"{type(projection).__qualname__}(points=0, output_enabled=False)"
    )
    matching = SweepProjection(points=0, output_enabled=False)
    assert projection == matching
    assert hash(projection) == hash(matching)
    assert not hasattr(projection, "__dict__")
    with pytest.raises(FrozenInstanceError):
        projection.__setattr__("points", 1)
    assignments = state_projection_assignments(projection)
    target: DesiredState = state_projection_target(projection)
    assignments_target = target_from_state_projection_assignments(assignments)
    assert target.target_assignments() == assignments
    assert assignments_target.target_assignments() == assignments
    assert type(target) is type(assignments_target)


def test_state_projection_accepts_a_compile_free_runtime_layout() -> None:
    compiled_layout = declared_interface_layout(
        compile_interface(SweepContract)
    ).states[0]
    layout = StateProjectionLayout(
        fields=tuple(
            StateProjectionField(field.python_name, field.ref)
            for field in compiled_layout.fields
            if field.python_name == "points"
        ),
        constants=compiled_layout.constants,
    )

    @instrument_state_projection(layout)
    class SweepProjection:
        points: int = state_projection_field()

    projection = SweepProjection(points=3)

    assert state_projection_assignments(projection) == {
        declared_property_ref(SweepContract, SweepState, "points"): 3,
    }
    assert repr(projection) == f"{type(projection).__qualname__}(points=3)"


def test_discriminated_projection_includes_required_fields_and_constants() -> None:
    _, voltage_layout, _ = declared_interface_layout(
        compile_interface(SourceContract)
    ).states

    @instrument_state_projection(voltage_layout)
    class VoltageProjection:
        range: Quantity
        level: Quantity
        output_enabled: bool = state_projection_field()

    projection = VoltageProjection(
        range=Quantity(1, "V"),
        level=Quantity(0.1, "V"),
        output_enabled=True,
    )

    assert state_projection_assignments(projection) == {
        declared_discriminator_ref(SourceContract): "voltage",
        declared_property_ref(SourceContract, VoltageState, "range"): Quantity(1, "V"),
        declared_property_ref(SourceContract, VoltageState, "level"): Quantity(
            0.1,
            "V",
        ),
        declared_property_ref(
            SourceContract,
            SourceCommonState,
            "output_enabled",
        ): True,
    }
    assert repr(projection) == (
        f"{type(projection).__qualname__}("
        "output_enabled=True, "
        f"range={projection.range!r}, level={projection.level!r})"
    )


def test_separate_compilations_do_not_share_mutable_models() -> None:
    first = compile_interface(SweepContract)
    second = compile_interface(SweepContract)

    assert first.spec is not second.spec
    first.spec.properties[0].label = "changed"
    assert second.spec.properties[0].label == "Start frequency"


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
