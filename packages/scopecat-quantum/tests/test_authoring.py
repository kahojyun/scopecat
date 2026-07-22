from __future__ import annotations

import pytest
import scopecat as sc
from scopecat import Quantity

from scopecat_quantum import authoring
from scopecat_quantum._ids import AcquisitionSlotId, QubitId
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
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
    declaration = authoring._close_program(
        "x-count",
        authoring.sequence(
            authoring.repeat(x(q0), x_count),
            readout,
        ),
    )
    return declaration, x_count, readout.result


def test_symbolic_repeat_and_measurement_declare_typed_ports() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()

    assert declaration.id == "x-count"
    assert declaration.inputs == (x_count,)
    assert x_count.id == "x_count"
    assert x_count.kind is GateParameterKind.INTEGER
    assert tuple(declaration.results) == (raw_iq,)
    assert raw_iq.id == "raw_iq"
    assert raw_iq.qubit.id == "q0"
    assert raw_iq.acquisition_kind is AcquisitionKind.INTEGRATED_IQ
    assert raw_iq.acquisition_slot_id == AcquisitionSlotId("raw_iq")


def test_two_qubit_gate_declares_ordered_unique_operands() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    cz = authoring.gate("cz", arity=2)

    bound = authoring.bind(authoring._close_program("cz", cz(q0, q1)))
    [call] = bound.verified.operations

    assert isinstance(cz, authoring.TwoQubitGate)
    assert isinstance(call, GateCall)
    assert call.qubits == (QubitId("q0"), QubitId("q1"))
    with pytest.raises(ValueError, match="operands must be unique"):
        cz(q0, q0)


def test_literal_zero_repeat_elides_dead_inputs_and_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    declaration = authoring._close_program(
        "dead-drive",
        authoring.repeat(drive(q0, amplitude=amplitude), 0),
    )

    bound = authoring.bind(declaration)

    assert declaration.inputs == ()
    assert bound.gate_definitions == ()
    assert bound.verified.operations == ()


def test_literal_zero_pulse_repeat_elides_inputs_but_retains_signal_owners() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.input(
        "amplitude",
        sc.ScalarType(sc.QuantityType(unit="arb")),
    )
    dead_pulse = authoring.repeat(
        authoring.play(
            authoring.drive(q0),
            authoring.constant(
                duration=Quantity(8, "ns"),
                amplitude=amplitude,
            ),
        ),
        0,
    )

    with pytest.raises(ValueError, match="undeclared formal elements: 'q0'"):
        authoring.pulse_template("dead-pulse", dead_pulse, elements=())

    template = authoring.pulse_template("dead-pulse", dead_pulse, elements=(q0,))
    assert template.inputs == ()


def test_implemented_gate_only_tightens_pulse_repeat_inputs() -> None:
    q0 = authoring.qubit("q0")
    gate_value = authoring.scalar_input("gate_value", GateParameterKind.INTEGER)
    pulse_count = authoring.input(
        "pulse_count",
        sc.ScalarType(sc.IntType()),
    )
    custom = authoring.single_qubit_gate(
        "custom",
        parameters={"value": GateParameterKind.INTEGER},
    )
    pulse = authoring.repeat(
        authoring.play(
            authoring.drive(q0),
            authoring.constant(
                duration=Quantity(8, "ns"),
                amplitude=Quantity(0.2, "arb"),
            ),
        ),
        pulse_count,
    )
    declaration = authoring._close_program(
        "implemented-repeat-inputs",
        authoring.implements(custom(q0, value=gate_value), pulse),
    )

    assert declaration.inputs == (gate_value, pulse_count)
    authoring.bind(declaration, {"gate_value": -1, "pulse_count": 1})
    with pytest.raises(
        authoring.ProgramBindingError,
        match=r"bindings\.pulse_count",
    ):
        authoring.bind(declaration, {"gate_value": -1, "pulse_count": -1})


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_symbolic_repeat_rejects_invalid_bound_counts(count: object) -> None:
    declaration, _x_count, _raw_iq = _x_count_declaration()

    with pytest.raises(
        authoring.ProgramBindingError,
        match=r"bindings\.x_count",
    ):
        authoring.bind(
            declaration,
            {"x_count": count},
        )


@pytest.mark.parametrize("count", [-1, True])
def test_repeat_rejects_invalid_literal_counts(count: int) -> None:
    q0 = authoring.qubit("q0")
    x = authoring.single_qubit_gate("x")

    with pytest.raises(ValueError, match="non-negative integer"):
        authoring.repeat(x(q0), count)


def test_repeat_rejects_non_integer_input_and_unnamed_result_axis() -> None:
    q0 = authoring.qubit("q0")
    angle = authoring.scalar_input("theta", GateParameterKind.ANGLE)

    with pytest.raises(TypeError, match="integer kind"):
        authoring.repeat(authoring.single_qubit_gate("x")(q0), angle)
    with pytest.raises(ValueError, match="require an axis"):
        authoring.repeat(authoring.measure(q0, result="raw_iq"), 2)


def test_result_repeat_declares_one_axis_and_unique_physical_slots() -> None:
    q0 = authoring.qubit("q0")
    rounds = authoring.scalar_input("rounds", GateParameterKind.INTEGER)
    declaration = authoring._close_program(
        "repeated-readout",
        authoring.repeat(
            authoring.measure(q0, result="raw_iq"),
            rounds,
            axis="round",
        ),
    )

    [result] = declaration.results
    bound = authoring.bind(declaration, {"rounds": 3})
    measurements = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, Measure)
    )

    assert tuple((axis.id, axis.size, axis.kind) for axis in result.contract.axes) == (
        ("round", rounds, "repeat"),
    )
    assert tuple(
        operation.acquisition_slot_id.local_id for operation in measurements
    ) == (
        "raw_iq",
        "raw_iq",
        "raw_iq",
    )
    assert len({operation.acquisition_slot_id for operation in measurements}) == 3
    with pytest.raises(authoring.ProgramBindingError, match=r"bindings\.rounds"):
        authoring.bind(declaration, {"rounds": 0})


def test_nested_repeat_and_parallel_results_share_the_composition_tree() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    one_round = authoring.parallel(
        authoring.measure(q0, result="stabilizer_iq"),
        authoring.measure(q1, result="stabilizer_iq"),
        axis="qubit",
        axis_kind="entity",
    )
    declaration = authoring._close_program(
        "stabilizer-rounds",
        authoring.repeat(one_round, 2, axis="round"),
    )

    [result] = declaration.results
    bound = authoring.bind(declaration)

    assert tuple((axis.id, axis.size, axis.kind) for axis in result.contract.axes) == (
        ("round", 2, "repeat"),
        ("qubit", 2, "entity"),
    )
    measurements = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, Measure)
    )
    assert len(measurements) == 4
    assert len({operation.acquisition_slot_id for operation in measurements}) == 4


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

    declaration = authoring._close_program("rx", rx(q0, theta=theta))
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
        authoring._close_program("duplicate-results", authoring.sequence(first, second))


def test_program_rejects_conflicting_gate_definitions() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.single_qubit_gate("custom")
    second = authoring.single_qubit_gate(
        "custom",
        parameters={"value": GateParameterKind.NUMBER},
    )

    with pytest.raises(ValueError, match="conflicting definitions"):
        authoring._close_program(
            "conflicting-gates",
            authoring.sequence(first(q0), second(q0, value=1.0)),
        )


def test_domain_execution_requires_exact_handle_bindings() -> None:
    declaration, x_count, raw_iq = _x_count_declaration()
    program = authoring._domain_program(declaration)
    products = (
        sc.module_body(id="test.quantum.bindings")
        .product("integrated_iq_shots")
        .build()
    )

    with pytest.raises(ValueError, match="bind every declared port"):
        authoring._domain_execution(
            program,
            results={raw_iq: products.products["integrated_iq_shots"]},
        )
    with pytest.raises(ValueError, match="bind every declared result"):
        authoring._domain_execution(
            program,
            inputs={x_count: 1},
        )


def test_domain_execution_rejects_forged_ports_and_normalizes_number_literal() -> None:
    q0 = authoring.qubit("q0")
    amplitude = authoring.scalar_input("amplitude", GateParameterKind.NUMBER)
    drive = authoring.single_qubit_gate(
        "drive",
        parameters={"amplitude": GateParameterKind.NUMBER},
    )
    readout = authoring.measure(q0, result="iq")
    declaration = authoring._close_program(
        "number-input",
        authoring.sequence(drive(q0, amplitude=amplitude), readout),
    )
    program = authoring._domain_program(declaration)
    products = sc.module_body(id="test.quantum.number-input").product("iq").build()

    execution = authoring._domain_execution(
        program,
        inputs={amplitude: 1},
        results={readout.result: products.products["iq"]},
    )
    assert execution.input_bindings == (("amplitude", 1.0),)

    forged = sc.domain_program(
        declaration.id,
        dialect_id=authoring.QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=authoring.QUANTUM_PROGRAM_DIALECT_VERSION,
        body=declaration,
        inputs={"amplitude": sc.ScalarType(sc.IntType())},
        results={"iq": readout.result},
    )
    with pytest.raises(ValueError, match="ports do not match"):
        authoring._domain_execution(
            forged,
            inputs={amplitude: 1},
            results={readout.result: products.products["iq"]},
        )
