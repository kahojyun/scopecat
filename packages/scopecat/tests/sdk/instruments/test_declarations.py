from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, assert_type

import pytest

from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments import (
    acquisition as expected_acquisition,
)
from scopecat.sdk.instruments import (
    acquisition_axis as expected_axis,
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
    interface as expected_interface,
)
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    acquisition,
    axis,
    compile_interface,
    declared_acquisition_ref,
    declared_interface_ref,
    declared_property_ref,
    declared_result_ref,
    instrument_interface,
    instrument_result,
    instrument_state,
    member,
    result,
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
