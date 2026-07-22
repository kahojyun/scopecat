"""Fixed-patch stabilizer rounds through the shared quantum domain compiler."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q

from quantum_lab_demo.experiments.ids import TOY_SURFACE_CODE_ROUND_TEMPLATE_ID

_READOUT_DURATION = sc.Quantity(24, "ns")
_READOUT_AMPLITUDE = sc.Quantity(0.3, "arb")
_COUPLER_AMPLITUDE = sc.Quantity(0.03, "arb")
_CYCLE_TIME_DEFAULT = sc.Quantity(32, "ns")

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))


def _readout_branch(qubit: q.Qubit) -> q.QuantumFragment:
    return q.parallel(
        q.play(
            q.readout(qubit),
            q.constant(
                duration=_READOUT_DURATION,
                amplitude=_READOUT_AMPLITUDE,
            ),
        ),
        q.acquire(
            qubit,
            duration=_READOUT_DURATION,
            result="stabilizer_iq",
        ),
    )


@q.program(id="toy-surface-code-round")
def toy_surface_code_round_program(
    data_0: q.Qubit,
    data_1: q.Qubit,
    ancilla_0: q.Qubit,
    ancilla_1: q.Qubit,
    coupler_01: q.Coupler,
    coupler_23: q.Coupler,
    rounds: Annotated[int, sc.IntType(minimum=1)],
    cycle_time: Annotated[sc.Quantity, sc.QuantityType(unit="ns")],
) -> q.QuantumFragment:
    """Collect a fixed four-qubit patch as round-by-qubit IQ results."""

    entangling_step = q.parallel(
        q.play(
            q.flux(coupler_01),
            q.constant(duration=cycle_time, amplitude=_COUPLER_AMPLITUDE),
        ),
        q.play(
            q.flux(coupler_23),
            q.constant(duration=cycle_time, amplitude=_COUPLER_AMPLITUDE),
        ),
    )
    patch_readout = q.parallel(
        _readout_branch(data_0),
        _readout_branch(data_1),
        _readout_branch(ancilla_0),
        _readout_branch(ancilla_1),
        axis="qubit",
        axis_kind="entity",
    )
    return q.repeat(
        q.sequence(entangling_step, patch_readout),
        rounds,
        axis="round",
    )


@sc.template(
    id=TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
    kind="toy_surface_code_round",
    label="toy surface-code round",
    description=("Run a fixed four-qubit patch with recursive round-by-qubit readout."),
)
def TOY_SURFACE_CODE_ROUND_TEMPLATE(
    data_0: Annotated[sc.Input[str], _QUBIT] = "q0",
    data_1: Annotated[sc.Input[str], _QUBIT] = "q1",
    ancilla_0: Annotated[sc.Input[str], _QUBIT] = "q2",
    ancilla_1: Annotated[sc.Input[str], _QUBIT] = "q3",
    coupler_01: Annotated[sc.Input[str], _COUPLER] = "coupler-q0-q1",
    coupler_23: Annotated[sc.Input[str], _COUPLER] = "coupler-q2-q3",
    rounds: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 3,
    cycle_time: Annotated[
        sc.Input[sc.Quantity],
        sc.QuantityType(unit="ns"),
    ] = _CYCLE_TIME_DEFAULT,
    shots: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 8,
) -> sc.ExperimentBody:
    """Run one fixed patch; ``rounds`` and ``shots`` scale its recursive result."""

    call = toy_surface_code_round_program(
        data_0=data_0,
        data_1=data_1,
        ancilla_0=ancilla_0,
        ancilla_1=ancilla_1,
        coupler_01=coupler_01,
        coupler_23=coupler_23,
        rounds=rounds,
        cycle_time=cycle_time,
        shots=shots,
    )
    return sc.experiment(call).record_product(
        call.results.stabilizer_iq,
        record_id="stabilizer_iq",
    )


__all__ = [
    "TOY_SURFACE_CODE_ROUND_TEMPLATE",
    "toy_surface_code_round_program",
]
