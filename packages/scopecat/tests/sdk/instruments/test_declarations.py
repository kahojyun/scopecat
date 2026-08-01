from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, assert_type

import pytest

from scopecat.kernel.quantity import Quantity
from scopecat.program.state import DesiredState
from scopecat.program.value_refs import ValueRef
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
    bool_property,
    enum_property,
    int_property,
    quantity_property,
)
from scopecat.sdk.instruments import (
    discriminated_state as expected_discriminated_state,
)
from scopecat.sdk.instruments import (
    interface as expected_interface,
)
from scopecat.sdk.instruments import state_case as expected_state_case
from scopecat.sdk.instruments import (
    state_discriminated_acquisition as expected_discriminated_acquisition,
)
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    acquisition,
    acquisition_case,
    axis,
    compile_interface,
    declared_acquisition_ref,
    declared_discriminator_ref,
    declared_interface_ref,
    declared_property_ref,
    declared_result_ref,
    declared_state_assignments,
    declared_state_target,
    discriminated_state,
    instrument_interface,
    instrument_result,
    instrument_state,
    interface_discriminator,
    member,
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
class CurrentResults:
    current: Annotated[
        float,
        result(
            id="monitored_current",
            unit="A",
            label="Current",
            description="Measured current.",
        ),
    ]


@instrument_result
@dataclass(frozen=True, slots=True)
class VoltageResults:
    voltage: Annotated[
        float,
        result(
            id="monitored_voltage",
            unit="V",
            label="Voltage",
            description="Measured voltage.",
        ),
    ]


@dataclass(frozen=True, slots=True)
class MonitorResultShape:
    current: float | None
    voltage: float | None


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
            acquisition_case("voltage", CurrentResults),
            acquisition_case("current", VoltageResults),
        ),
    )
    def monitor(self) -> MonitorResultShape: ...


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
