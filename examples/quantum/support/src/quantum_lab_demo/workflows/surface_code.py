"""Fixed-patch stabilizer rounds through the shared quantum domain compiler."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q

TOY_SURFACE_CODE_ROUND_TEMPLATE_ID = "quantum_lab_demo.workflows.toy_surface_code_round"

_READOUT_DURATION = sc.Quantity(24, "ns")
_READOUT_AMPLITUDE = sc.Quantity(0.3, "arb")
_COUPLER_AMPLITUDE = sc.Quantity(0.03, "arb")
_CYCLE_TIME_DEFAULT = sc.Quantity(32, "ns")


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
def toy_surface_code_round_template(
    data_0: q.QubitInput = "q0",
    data_1: q.QubitInput = "q1",
    ancilla_0: q.QubitInput = "q2",
    ancilla_1: q.QubitInput = "q3",
    coupler_01: q.CouplerInput = "coupler-q0-q1",
    coupler_23: q.CouplerInput = "coupler-q2-q3",
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
    ).with_shots(shots)
    return sc.experiment(call).record_product(call.results.stabilizer_iq)


__all__ = [
    "TOY_SURFACE_CODE_ROUND_TEMPLATE_ID",
    "toy_surface_code_round_program",
    "toy_surface_code_round_template",
]
