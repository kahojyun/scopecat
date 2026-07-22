"""Fixed multi-lane pulse/readout rounds through the quantum domain compiler."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

FIXED_PATCH_READOUT_TEMPLATE_ID = "quantum_lab_demo.workflows.fixed_patch_readout"

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
            result="patch_iq",
        ),
    )


@q.program(id="fixed-patch-readout")
def fixed_patch_readout_program(
    qubit_0: q.Qubit,
    qubit_1: q.Qubit,
    qubit_2: q.Qubit,
    qubit_3: q.Qubit,
    coupler_01: q.Coupler,
    coupler_23: q.Coupler,
    rounds: Annotated[int, sc.IntType(minimum=1)],
    cycle_time: Annotated[sc.Quantity, sc.QuantityType(unit="ns")],
) -> q.QuantumFragment:
    """Exercise fixed parallel lanes and collect round-by-qubit IQ results."""

    coupler_step = q.parallel(
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
        _readout_branch(qubit_0),
        _readout_branch(qubit_1),
        _readout_branch(qubit_2),
        _readout_branch(qubit_3),
        axis="qubit",
        axis_kind="entity",
    )
    return q.repeat(
        q.sequence(coupler_step, patch_readout),
        rounds,
        axis="round",
    )


@sc.template(
    id=FIXED_PATCH_READOUT_TEMPLATE_ID,
    kind="fixed_patch_readout",
    label="fixed patch readout",
    description="Exercise fixed parallel lanes with recursive round-by-qubit readout.",
)
def fixed_patch_readout_template(
    qubit_0: q.QubitInput = "q0",
    qubit_1: q.QubitInput = "q1",
    qubit_2: q.QubitInput = "q2",
    qubit_3: q.QubitInput = "q3",
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

    call = (
        fixed_patch_readout_program(
            qubit_0=qubit_0,
            qubit_1=qubit_1,
            qubit_2=qubit_2,
            qubit_3=qubit_3,
            coupler_01=coupler_01,
            coupler_23=coupler_23,
            rounds=rounds,
            cycle_time=cycle_time,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(shots)
    )
    return sc.experiment(call).record_product(call.results.patch_iq)


__all__ = [
    "FIXED_PATCH_READOUT_TEMPLATE_ID",
    "fixed_patch_readout_program",
    "fixed_patch_readout_template",
]
