from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
import scopecat as sc
from scopecat import Quantity

from scopecat_quantum import authoring
from scopecat_quantum._ids import AcquisitionSlotId, QubitId
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import (
    CircuitVerificationError,
    Measure,
    Parallel,
    Sequence,
    iter_circuit_operations,
)
from scopecat_quantum.gates import GateCall, GateParameterKind


def _x_count_declaration() -> tuple[
    authoring.Circuit,
    authoring.CircuitInput,
    authoring.CircuitResult,
]:
    q0 = authoring.qubit("q0")
    x_count = authoring.scalar_input("x_count", GateParameterKind.INTEGER)
    x = authoring.single_qubit_gate("x")
    readout = authoring.measure(q0, result="raw_iq")
    declaration = authoring.circuit(
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
        authoring.BoundCircuit,
        authoring.Circuit,
        authoring.CircuitFragment,
        authoring.CircuitInput,
        authoring.CircuitResult,
        authoring.Measurement,
        authoring.Qubit,
        authoring.SingleQubitGate,
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


def test_zero_repeat_materializes_as_no_gate_calls() -> None:
    declaration, _x_count, raw_iq = _x_count_declaration()

    bound = authoring.bind_circuit(declaration, {"x_count": 0})
    operations = tuple(iter_circuit_operations(bound.program.body))

    assert isinstance(bound.program.body, Sequence)
    assert operations == (
        Measure(
            id=operations[0].id,
            qubit=QubitId("q0"),
            acquisition_slot_id=raw_iq.acquisition_slot_id,
            acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        ),
    )
    assert bound.verified.operations == operations
    assert bound.results == (raw_iq,)


def test_literal_zero_repeat_elides_dead_inputs_and_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    declaration = authoring.circuit(
        "dead-drive",
        authoring.repeat(drive(q0, amplitude=amplitude), 0),
    )

    bound = authoring.bind_circuit(declaration)

    assert declaration.inputs == ()
    assert declaration.gate_definitions == ()
    assert bound.verified.operations == ()


def test_symbolic_repeat_materializes_unique_gate_occurrences() -> None:
    declaration, _x_count, _raw_iq = _x_count_declaration()

    bound = authoring.bind_circuit(declaration, {"x_count": 3})
    operations = tuple(iter_circuit_operations(bound.program.body))

    assert [type(operation) for operation in operations] == [
        GateCall,
        GateCall,
        GateCall,
        Measure,
    ]
    gate_calls = cast("tuple[GateCall, ...]", operations[:-1])
    assert [operation.gate_id.value for operation in gate_calls] == [
        "x",
        "x",
        "x",
    ]
    assert len({operation.id for operation in operations}) == 4


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_symbolic_repeat_rejects_invalid_bound_counts(count: object) -> None:
    declaration, _x_count, _raw_iq = _x_count_declaration()

    with pytest.raises(
        authoring.CircuitBindingError,
        match="non-negative integer",
    ):
        authoring.bind_circuit(
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


def test_symbolic_angle_binding_uses_existing_verification_and_canonicalization() -> (
    None
):
    q0 = authoring.qubit("q0")
    theta = authoring.scalar_input("theta", GateParameterKind.ANGLE)
    rx = authoring.single_qubit_gate(
        "rx",
        parameters={"theta": GateParameterKind.ANGLE},
    )
    declaration = authoring.circuit("rx", rx(q0, theta=theta))

    bound = authoring.bind_circuit(declaration, {"theta": Quantity(180, "deg")})
    operation = bound.verified.operations[0]

    assert isinstance(operation, GateCall)
    assert operation.arguments[0].id == "theta"
    assert operation.arguments[0].value == Quantity(180, "deg").to("rad")


def test_symbolic_gate_parameter_kind_is_checked_at_authoring_and_binding() -> None:
    q0 = authoring.qubit("q0")
    integer = authoring.scalar_input("count", GateParameterKind.INTEGER)
    angle = authoring.scalar_input("theta", GateParameterKind.ANGLE)
    rx = authoring.single_qubit_gate(
        "rx",
        parameters={"theta": GateParameterKind.ANGLE},
    )

    with pytest.raises(TypeError, match="requires 'angle'"):
        rx(q0, theta=integer)

    declaration = authoring.circuit("rx", rx(q0, theta=angle))
    with pytest.raises(CircuitVerificationError) as caught:
        authoring.bind_circuit(declaration, {"theta": 1.0})
    assert {issue.code for issue in caught.value.issues} == {
        "circuit_gate_argument_type_mismatch"
    }


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


def test_bind_circuit_requires_exact_named_bindings() -> None:
    declaration, _x_count, _raw_iq = _x_count_declaration()

    with pytest.raises(authoring.CircuitBindingError, match="missing 'x_count'"):
        authoring.bind_circuit(declaration)
    with pytest.raises(authoring.CircuitBindingError, match="unknown 'other'"):
        authoring.bind_circuit(declaration, {"x_count": 1, "other": 2})


def test_parallel_disjoint_qubits_materialize_as_existing_parallel_ir() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    x = authoring.single_qubit_gate("x")
    declaration = authoring.circuit("parallel", authoring.parallel(x(q0), x(q1)))

    bound = authoring.bind_circuit(declaration)

    assert isinstance(bound.program.body, Parallel)
    gate_calls = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, GateCall)
    )
    assert [operation.qubits for operation in gate_calls] == [
        (QubitId("q0"),),
        (QubitId("q1"),),
    ]


def test_parallel_conflicts_are_reported_by_existing_circuit_verifier() -> None:
    q0 = authoring.qubit("q0")
    x = authoring.single_qubit_gate("x")
    declaration = authoring.circuit("conflict", authoring.parallel(x(q0), x(q0)))

    with pytest.raises(CircuitVerificationError) as caught:
        authoring.bind_circuit(declaration)

    assert {issue.code for issue in caught.value.issues} == {"parallel_qubit_conflict"}


def test_circuit_rejects_duplicate_result_ports() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.measure(q0, result="raw_iq")
    second = authoring.measure(q0, result="raw_iq")

    with pytest.raises(ValueError, match="duplicate result ids"):
        authoring.circuit("duplicate-results", authoring.sequence(first, second))


def test_circuit_rejects_conflicting_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.single_qubit_gate("custom")
    second = authoring.single_qubit_gate(
        "custom",
        parameters={"value": GateParameterKind.NUMBER},
    )

    with pytest.raises(ValueError, match="conflicting definitions"):
        authoring.circuit(
            "conflicting-gates",
            authoring.sequence(first(q0), second(q0, value=1.0)),
        )


def test_circuit_projects_to_typed_core_domain_program_and_call() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()
    point_value = sc.point("x_count", sc.ScalarType(sc.IntType(minimum=0)))

    program = authoring.circuit_domain_program(declaration)
    call = authoring.circuit_domain_call(
        "acquire",
        program,
        inputs={x_count: point_value},
        results={raw_iq: "integrated_iq_shots"},
    )

    assert program.dialect_id == authoring.QUANTUM_CIRCUIT_DIALECT_ID
    assert program.body is declaration
    assert program.input_ports[0].value_type == sc.ScalarType(sc.IntType(minimum=0))
    assert program.result_ports[0].contract is raw_iq
    assert call.input_bindings == (("x_count", point_value),)
    assert call.result_bindings[0][0] == "raw_iq"
    assert call.result_bindings[0][1].local_id == "integrated_iq_shots"


def test_circuit_domain_call_requires_exact_handle_bindings() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()
    program = authoring.circuit_domain_program(declaration)

    with pytest.raises(ValueError, match="bind every declared CircuitInput"):
        authoring.circuit_domain_call(
            "missing-input",
            program,
            results={raw_iq: "integrated_iq_shots"},
        )
    with pytest.raises(ValueError, match="bind every declared CircuitResult"):
        authoring.circuit_domain_call(
            "missing-result",
            program,
            inputs={x_count: 1},
        )
    with pytest.raises(TypeError, match="inputs must be a mapping"):
        authoring.circuit_domain_call(
            "invalid-inputs",
            program,
            inputs=[],  # pyright: ignore[reportArgumentType]
            results={raw_iq: "integrated_iq_shots"},
        )
    with pytest.raises(TypeError, match="quantum circuit domain program"):
        authoring.circuit_domain_call(
            "invalid-program",
            object(),  # pyright: ignore[reportArgumentType]
        )


def test_circuit_domain_call_rejects_forged_ports_and_normalizes_number_literal() -> (
    None
):
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    readout = authoring.measure(q0, result="iq")
    declaration = authoring.circuit(
        "number-input",
        authoring.sequence(drive(q0, amplitude=amplitude), readout),
    )
    program = authoring.circuit_domain_program(declaration)

    call = authoring.circuit_domain_call(
        "execute",
        program,
        inputs={amplitude: 1},
        results={readout.result: "iq"},
    )
    assert call.input_bindings == (("amplitude", 1.0),)

    forged = sc.domain_program(
        declaration.id,
        dialect_id=authoring.QUANTUM_CIRCUIT_DIALECT_ID,
        dialect_version=authoring.QUANTUM_CIRCUIT_DIALECT_VERSION,
        body=declaration,
        inputs={"amplitude": sc.ScalarType(sc.IntType())},
        results={"iq": readout.result},
    )
    with pytest.raises(ValueError, match="ports do not match"):
        authoring.circuit_domain_call(
            "forged",
            forged,
            inputs={amplitude: 1},
            results={readout.result: "iq"},
        )
