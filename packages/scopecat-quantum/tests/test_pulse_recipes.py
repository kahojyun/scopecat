from __future__ import annotations

from dataclasses import dataclass

import pytest
from scopecat import Quantity

from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    CouplerId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import CircuitProgram, Measure, verify_circuit_program
from scopecat_quantum.circuits import Sequence as CircuitSequence
from scopecat_quantum.gates import GateArgument, GateCall, GateParameterKind
from scopecat_quantum.pulse_implementations import (
    GatePulseImplementationArgument,
    GatePulseImplementationKey,
    MeasurementPulseImplementationKey,
)
from scopecat_quantum.pulse_recipes import (
    PulseRecipeMap,
    PulseRecipeProfile,
    gate_pulse_recipe,
    map_qubit_pulse_recipes,
    measurement_pulse_recipe,
)
from scopecat_quantum.pulses import Constant, Play, iter_pulse_leaves


@dataclass(frozen=True, slots=True)
class _QubitRow:
    qubit: QubitId
    drive_amplitude: Quantity
    readout_amplitude: Quantity


@dataclass(frozen=True, slots=True)
class _Parameters:
    qubits: tuple[_QubitRow, ...]


X = quantum.single_qubit_gate("x")
RX = quantum.single_qubit_gate(
    "rx",
    parameters={"theta": GateParameterKind.ANGLE},
)
CZ = quantum.two_qubit_gate("cz")


@gate_pulse_recipe(of=X, id="x.constant")
def _x_recipe(
    row: _QubitRow,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return quantum.play(
        quantum.drive(target),
        quantum.constant(
            duration=Quantity(16, "ns"),
            amplitude=row.drive_amplitude,
        ),
    )


@measurement_pulse_recipe(
    kind=AcquisitionKind.INTEGRATED_IQ,
    id="readout.integrated-iq",
)
def _readout_recipe(
    row: _QubitRow,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    duration = Quantity(800, "ns")
    return quantum.parallel(
        quantum.play(
            quantum.readout(target),
            quantum.constant(
                duration=duration,
                amplitude=row.readout_amplitude,
            ),
        ),
        quantum.acquire(target, duration=duration, result="result"),
    )


@gate_pulse_recipe(of=RX, id="rx.constant")
def _rx_recipe(
    row: _QubitRow,
    target: quantum.Qubit,
    *,
    theta: Quantity,
) -> quantum.QuantumFragment:
    return quantum.play(
        quantum.drive(target),
        quantum.constant(
            duration=Quantity(16, "ns"),
            amplitude=row.drive_amplitude,
            phase=theta,
        ),
    )


_PROFILE = PulseRecipeProfile[_Parameters](
    map_qubit_pulse_recipes(
        rows=lambda parameters: parameters.qubits,
        qubit=lambda row: row.qubit,
        gates=(_x_recipe, _rx_recipe),
        measurements=(_readout_recipe,),
    )
)


def _parameters(*, q0_amplitude: float = 0.2) -> _Parameters:
    return _Parameters(
        (
            _QubitRow(
                QubitId("q1"),
                Quantity(0.3, "arb"),
                Quantity(0.4, "arb"),
            ),
            _QubitRow(
                QubitId("q0"),
                Quantity(q0_amplitude, "arb"),
                Quantity(0.35, "arb"),
            ),
        )
    )


def _x_call(operation_id: str, qubit_id: str) -> GateCall:
    return GateCall(
        CircuitOperationId(operation_id),
        X.definition.id,
        (QubitId(qubit_id),),
    )


def _measurement(operation_id: str, qubit_id: str) -> Measure:
    return Measure(
        CircuitOperationId(operation_id),
        QubitId(qubit_id),
        AcquisitionSlotId(operation_id),
        AcquisitionKind.INTEGRATED_IQ,
    )


def _circuit(*operations: GateCall | Measure):
    return verify_circuit_program(
        CircuitProgram(CircuitId("recipe-test"), CircuitSequence(operations)),
        (X.definition, RX.definition, CZ.definition),
    )


def test_profile_maps_only_operations_present_in_the_bound_circuit() -> None:
    circuit = _circuit(
        _x_call("x-q1", "q1"),
        _measurement("measure-q0", "q0"),
    )

    resolved = _PROFILE.materialize(_parameters(), circuit)

    assert tuple(implementation.key for implementation in resolved.gates) == (
        GatePulseImplementationKey(X.definition.id, (QubitId("q1"),)),
    )
    assert tuple(implementation.id.value for implementation in resolved.gates) == (
        "x.constant[q1]",
    )
    assert tuple(implementation.key for implementation in resolved.measurements) == (
        MeasurementPulseImplementationKey(
            QubitId("q0"),
            AcquisitionKind.INTEGRATED_IQ,
        ),
    )
    assert resolved.measurements[0].pulse_template.acquisition_slots[0].id == (
        AcquisitionSlotId("result")
    )


def test_repeated_exact_gate_calls_materialize_one_reusable_implementation() -> None:
    circuit = _circuit(
        _x_call("first", "q0"),
        _x_call("second", "q0"),
    )

    resolved = _PROFILE.materialize(_parameters(), circuit)

    assert len(resolved.gates) == 1


def test_actual_gate_arguments_are_forwarded_into_the_authored_fragment() -> None:
    call = GateCall(
        CircuitOperationId("rx-q0"),
        RX.definition.id,
        (QubitId("q0"),),
        (GateArgument("theta", Quantity(90, "deg")),),
    )

    resolved = _PROFILE.materialize(_parameters(), _circuit(call))

    [implementation] = resolved.gates
    assert implementation.key.arguments == (
        GatePulseImplementationArgument("theta", Quantity(90, "deg")),
    )
    [leaf] = iter_pulse_leaves(implementation.pulse_template.body)
    assert isinstance(leaf, Play)
    assert isinstance(leaf.envelope, Constant)
    assert leaf.envelope.phase == Quantity(90, "deg").to("rad")


def test_point_values_change_fingerprint_not_recipe_identity() -> None:
    circuit = _circuit(_x_call("x-q0", "q0"))
    baseline = _PROFILE.materialize(_parameters(), circuit)
    changed = _PROFILE.materialize(_parameters(q0_amplitude=0.25), circuit)

    [baseline_q0] = baseline.gates
    [changed_q0] = changed.gates
    assert (
        baseline_q0.id == changed_q0.id == _x_recipe.implementation_id((QubitId("q0"),))
    )
    assert baseline_q0.fingerprint != changed_q0.fingerprint


def test_gate_recipe_couplers_are_explicit_validated_resources() -> None:
    coupler_id = CouplerId("c01")

    @gate_pulse_recipe(of=CZ, id="cz.flux")
    def cz_recipe(
        row: _QubitRow,
        _control: quantum.Qubit,
        _target: quantum.Qubit,
        coupler: quantum.Coupler,
    ) -> quantum.QuantumFragment:
        return quantum.play(
            quantum.flux(coupler),
            quantum.constant(
                duration=Quantity(20, "ns"),
                amplitude=row.drive_amplitude,
            ),
        )

    mapping = PulseRecipeMap[_Parameters, _QubitRow](
        rows=lambda parameters: parameters.qubits[:1],
        operands=lambda _row: (QubitId("q0"), QubitId("q1")),
        resources=lambda _row: (coupler_id,),
        gates=(cz_recipe,),
    )
    call = GateCall(
        CircuitOperationId("cz"),
        CZ.definition.id,
        (QubitId("q0"), QubitId("q1")),
    )

    resolved = mapping.materialize(_parameters(), _circuit(call))

    assert resolved.gates[0].resources == (coupler_id,)


def test_profile_rejects_duplicate_recipe_identity() -> None:
    mapping: PulseRecipeMap[_Parameters, _QubitRow] = map_qubit_pulse_recipes(
        rows=lambda parameters: parameters.qubits,
        qubit=lambda row: row.qubit,
        gates=(_x_recipe,),
    )

    with pytest.raises(ValueError, match="recipe ids must be unique"):
        PulseRecipeProfile[_Parameters](mapping, mapping)
