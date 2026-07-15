from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
import scopecat as sc
from scopecat import Quantity

from scopecat_quantum import authoring
from scopecat_quantum._ids import AcquisitionSlotId, QubitId
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.gates import GateCall, GateParameterKind


def _x_count_declaration() -> tuple[
    authoring.Program,
    authoring.CircuitInput,
    authoring.MeasurementResult,
]:
    q0 = authoring.qubit("q0")
    x_count = authoring.scalar_input("x_count", GateParameterKind.INTEGER)
    x = authoring.single_qubit_gate("x")
    readout = authoring.measure(q0, result="raw_iq")
    declaration = authoring.program(
        "x-count",
        authoring.sequence(
            authoring.repeat(x(q0), x_count),
            readout,
        ),
    )
    return declaration, x_count, readout.result


@pytest.mark.parametrize(
    "handle_type",
    [
        authoring.BoundProgram,
        authoring.Program,
        authoring.Acquisition,
        authoring.CircuitFragment,
        authoring.CircuitInput,
        authoring.Coupler,
        authoring.MeasurementResult,
        authoring.Measurement,
        authoring.PulseEnvelope,
        authoring.PulseFragment,
        authoring.PulseTemplate,
        authoring.QuantumFragment,
        authoring.QuantumInput,
        authoring.Qubit,
        authoring.SingleQubitGate,
        authoring.TwoQubitGate,
    ],
)
def test_authoring_handles_are_opaque(handle_type: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="opaque handle"):
        handle_type()


def test_symbolic_repeat_and_measurement_declare_typed_ports() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()

    assert declaration.id == "x-count"
    assert declaration.inputs == (x_count,)
    assert x_count.id == "x_count"
    assert x_count.kind is GateParameterKind.INTEGER
    assert declaration.results == (raw_iq,)
    assert raw_iq.id == "raw_iq"
    assert raw_iq.qubit.id == "q0"
    assert raw_iq.acquisition_kind is AcquisitionKind.INTEGRATED_IQ
    assert raw_iq.acquisition_slot_id == AcquisitionSlotId("raw_iq")


def test_two_qubit_gate_declares_ordered_unique_operands() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    cz = authoring.gate("cz", arity=2)

    bound = authoring.bind(authoring.program("cz", cz(q0, q1)))
    [call] = bound.verified.operations

    assert isinstance(cz, authoring.TwoQubitGate)
    assert isinstance(call, GateCall)
    assert call.qubits == (QubitId("q0"), QubitId("q1"))
    with pytest.raises(ValueError, match="operands must be unique"):
        cz(q0, q0)
    with pytest.raises(ValueError, match="arity must be 1 or 2"):
        authoring.gate(  # pyright: ignore[reportCallIssue, reportArgumentType]
            "ccz",
            arity=3,  # pyright: ignore[reportArgumentType]
        )


def test_literal_zero_repeat_elides_dead_inputs_and_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    declaration = authoring.program(
        "dead-drive",
        authoring.repeat(drive(q0, amplitude=amplitude), 0),
    )

    bound = authoring.bind(declaration)

    assert declaration.inputs == ()
    assert declaration.gate_definitions == ()
    assert bound.verified.operations == ()


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_symbolic_repeat_rejects_invalid_bound_counts(count: object) -> None:
    declaration, _x_count, _raw_iq = _x_count_declaration()

    with pytest.raises(
        authoring.ProgramBindingError,
        match=r"bindings\.x_count",
    ):
        authoring.bind(
            declaration,
            cast("dict[str, int]", {"x_count": count}),
        )


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_repeat_rejects_invalid_literal_counts(count: object) -> None:
    q0 = authoring.qubit("q0")
    x = authoring.single_qubit_gate("x")

    with pytest.raises(ValueError, match="non-negative integer"):
        authoring.repeat(x(q0), cast("int", count))


def test_repeat_rejects_non_integer_input_and_measurement_results() -> None:
    q0 = authoring.qubit("q0")
    angle = authoring.scalar_input("theta", GateParameterKind.ANGLE)

    with pytest.raises(TypeError, match="integer kind"):
        authoring.repeat(authoring.single_qubit_gate("x")(q0), angle)
    with pytest.raises(ValueError, match="measurement results"):
        authoring.repeat(authoring.measure(q0, result="raw_iq"), 2)


def test_gate_parameter_inputs_are_checked_and_angle_values_are_canonicalized() -> None:
    q0 = authoring.qubit("q0")
    integer = authoring.scalar_input("count", GateParameterKind.INTEGER)
    theta = authoring.scalar_input("theta", GateParameterKind.ANGLE)
    rx = authoring.single_qubit_gate(
        "rx",
        parameters={"theta": GateParameterKind.ANGLE},
    )
    with pytest.raises(TypeError, match="requires 'angle'"):
        rx(q0, theta=integer)

    declaration = authoring.program("rx", rx(q0, theta=theta))
    bound = authoring.bind(declaration, {"theta": Quantity(180, "deg")})
    operation = bound.verified.operations[0]

    assert isinstance(operation, GateCall)
    assert operation.arguments[0].id == "theta"
    assert operation.arguments[0].value == Quantity(180, "deg").to("rad")


def test_gate_call_requires_exact_named_arguments() -> None:
    q0 = authoring.qubit("q0")
    rx = authoring.single_qubit_gate(
        "rx",
        parameters={"theta": GateParameterKind.ANGLE},
    )

    with pytest.raises(ValueError, match="missing 'theta'"):
        rx(q0)
    with pytest.raises(ValueError, match="unknown 'phase'"):
        rx(q0, theta=Quantity(0, "rad"), phase=0)


def test_program_rejects_duplicate_result_ports() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.measure(q0, result="raw_iq")
    second = authoring.measure(q0, result="raw_iq")

    with pytest.raises(ValueError, match="duplicate result ids"):
        authoring.program("duplicate-results", authoring.sequence(first, second))


def test_program_rejects_conflicting_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.single_qubit_gate("custom")
    second = authoring.single_qubit_gate(
        "custom",
        parameters={"value": GateParameterKind.NUMBER},
    )

    with pytest.raises(ValueError, match="conflicting definitions"):
        authoring.program(
            "conflicting-gates",
            authoring.sequence(first(q0), second(q0, value=1.0)),
        )


def test_domain_call_requires_exact_handle_bindings() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()
    program = authoring.domain_program(declaration)

    with pytest.raises(ValueError, match="bind every declared input"):
        authoring.domain_call(
            "missing-input",
            program,
            results={raw_iq: "integrated_iq_shots"},
        )
    with pytest.raises(ValueError, match="bind every declared result"):
        authoring.domain_call(
            "missing-result",
            program,
            inputs={x_count: 1},
        )
    with pytest.raises(TypeError, match="inputs must be a mapping"):
        authoring.domain_call(
            "invalid-inputs",
            program,
            inputs=[],  # pyright: ignore[reportArgumentType]
            results={raw_iq: "integrated_iq_shots"},
        )
    with pytest.raises(TypeError, match="quantum program domain program"):
        authoring.domain_call(
            "invalid-program",
            object(),  # pyright: ignore[reportArgumentType]
        )


def test_domain_call_rejects_forged_ports_and_normalizes_number_literal() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    readout = authoring.measure(q0, result="iq")
    declaration = authoring.program(
        "number-input",
        authoring.sequence(drive(q0, amplitude=amplitude), readout),
    )
    program = authoring.domain_program(declaration)

    call = authoring.domain_call(
        "execute",
        program,
        inputs={amplitude: 1},
        results={readout.result: "iq"},
    )
    assert call.input_bindings == (("amplitude", 1.0),)

    forged = sc.domain_program(
        declaration.id,
        dialect_id=authoring.QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=authoring.QUANTUM_PROGRAM_DIALECT_VERSION,
        body=declaration,
        inputs={"amplitude": sc.ScalarType(sc.IntType())},
        results={"iq": readout.result},
    )
    with pytest.raises(ValueError, match="ports do not match"):
        authoring.domain_call(
            "forged",
            forged,
            inputs={amplitude: 1},
            results={readout.result: "iq"},
        )
