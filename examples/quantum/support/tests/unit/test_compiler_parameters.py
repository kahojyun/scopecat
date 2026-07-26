from __future__ import annotations

from scopecat import Quantity
from scopecat.kernel.entity import EntityRef
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import (
    CircuitProgram,
    Measure,
    VerifiedCircuitProgram,
    verify_circuit_program,
)
from scopecat_quantum.circuits import (
    Sequence as CircuitSequence,
)
from scopecat_quantum.gates import GateCall
from scopecat_quantum.standard_gates import X90, X

from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE


def _circuit(*operations: GateCall | Measure) -> VerifiedCircuitProgram:
    return verify_circuit_program(
        CircuitProgram(CircuitId("compiler-parameters"), CircuitSequence(operations)),
        (X.definition, X90.definition),
    )


def _qubit_row(qubit: str, *, beta: float) -> dict[str, object]:
    return {
        "qubit": EntityRef(id=qubit, kind="logical_qubit"),
        "x_duration": Quantity(32, "ns"),
        "x_amplitude": Quantity(0.4, "arb"),
        "quarter_turn_duration": Quantity(16, "ns"),
        "quarter_turn_amplitude": Quantity(0.2, "arb"),
        "quarter_turn_sigma": Quantity(4, "ns"),
        "drag_beta": Quantity(beta, "ns"),
        "readout_duration": Quantity(800, "ns"),
        "readout_amplitude": Quantity(0.3, "arb"),
    }


def test_point_effective_snapshot_is_order_independent() -> None:
    rows = (_qubit_row("q0", beta=0.5), _qubit_row("q1", beta=0.25))

    forward = QuantumCompilerParameters.from_qubit_rows(rows)
    reversed_rows = QuantumCompilerParameters.from_qubit_rows(tuple(reversed(rows)))

    assert forward == reversed_rows
    assert forward.fingerprint == reversed_rows.fingerprint
    assert forward.qubits[0].qubit == QubitId("q0")
    assert forward.qubits[0].drag_beta == Quantity(0.5, "ns")


def test_overlay_changes_resolution_not_recipe_identity() -> None:
    baseline = QuantumCompilerParameters.from_qubit_rows(
        (_qubit_row("q0", beta=0.5), _qubit_row("q1", beta=0.25))
    )
    overlaid = QuantumCompilerParameters.from_qubit_rows(
        (_qubit_row("q0", beta=0.75), _qubit_row("q1", beta=0.25))
    )

    circuit = _circuit(
        GateCall(
            CircuitOperationId("x90-q0"),
            X90.definition.id,
            (QubitId("q0"),),
        )
    )
    [baseline_x90] = QUANTUM_PULSE_PROFILE.materialize(baseline, circuit).gates
    [overlaid_x90] = QUANTUM_PULSE_PROFILE.materialize(overlaid, circuit).gates

    assert baseline_x90.id == overlaid_x90.id
    assert baseline_x90.fingerprint != overlaid_x90.fingerprint
    assert baseline.fingerprint != overlaid.fingerprint


def test_profile_maps_only_bound_operations_to_parameter_rows() -> None:
    parameters = QuantumCompilerParameters.from_qubit_rows(
        (_qubit_row("q0", beta=0.5), _qubit_row("q1", beta=0.25))
    )

    circuit = _circuit(
        GateCall(CircuitOperationId("x-q0"), X.definition.id, (QubitId("q0"),)),
        GateCall(
            CircuitOperationId("x90-q1"),
            X90.definition.id,
            (QubitId("q1"),),
        ),
        Measure(
            CircuitOperationId("measure-q1"),
            QubitId("q1"),
            AcquisitionSlotId("result"),
            AcquisitionKind.INTEGRATED_IQ,
        ),
    )

    resolved = QUANTUM_PULSE_PROFILE.materialize(parameters, circuit)

    assert len(resolved.gates) == 2
    assert len(resolved.measurements) == 1
    assert {
        (implementation.key.gate_id.value, implementation.key.operands[0].value)
        for implementation in resolved.gates
    } == {
        ("x", "q0"),
        ("x90", "q1"),
    }
