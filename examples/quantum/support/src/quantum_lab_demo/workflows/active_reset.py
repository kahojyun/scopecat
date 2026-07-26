"""Bounded active reset for the fake realtime control target."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q
from scopecat_quantum.standard_gates import X

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

ACTIVE_RESET_TEMPLATE_ID = "quantum_lab_demo.workflows.active_reset"


@q.program(id="active-reset")
def active_reset_program(
    qubit: q.Qubit,
    rounds: Annotated[int, sc.IntType(minimum=1)],
) -> q.QuantumFragment:
    """Measure and conditionally apply X for a fixed number of rounds."""

    measured = q.measure(qubit, result="reset_iq", bit="reset_bit")
    return q.repeat(
        q.sequence(
            measured,
            q.when(measured.bit, X(qubit)),
        ),
        rounds,
        axis="round",
    )


@sc.template(
    id=ACTIVE_RESET_TEMPLATE_ID,
    kind="active_reset",
)
def active_reset_template(
    qubit: q.QubitInput = "q0",
    rounds: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 3,
    shots: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 2,
) -> sc.ExperimentBody:
    call = (
        active_reset_program(qubit=qubit, rounds=rounds)
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(shots)
    )
    return sc.experiment(call).record_product(call.results.reset_iq)


__all__ = [
    "ACTIVE_RESET_TEMPLATE_ID",
    "active_reset_program",
    "active_reset_template",
]
