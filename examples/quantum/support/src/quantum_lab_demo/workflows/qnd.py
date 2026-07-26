"""Repeated QND readout through the shared quantum domain compiler."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

QND_REPEATED_MEASUREMENT_TEMPLATE_ID = (
    "quantum_lab_demo.workflows.qnd_repeated_measurement"
)


@q.program(id="qnd-repeated-measurement")
def qnd_repeated_measurement_program(
    qubit: q.Qubit,
    rounds: Annotated[int, sc.IntType(minimum=1)],
) -> q.QuantumFragment:
    """Collect one logical IQ result over recursively repeated readout slots."""

    return q.repeat(
        q.measure(qubit, result="qnd_iq"),
        rounds,
        axis="round",
    )


@sc.template(
    id=QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    kind="qnd_repeated_measurement",
)
def qnd_repeated_measurement_template(
    qubit: q.QubitInput,
    rounds: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 4,
    shots: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 16,
) -> sc.ExperimentBody:
    """Run repeated readout as a shot-by-round dense result."""

    call = (
        qnd_repeated_measurement_program(
            qubit=qubit,
            rounds=rounds,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(shots)
    )
    return sc.experiment(call).record_product(call.results.qnd_iq)


__all__ = [
    "QND_REPEATED_MEASUREMENT_TEMPLATE_ID",
    "qnd_repeated_measurement_program",
    "qnd_repeated_measurement_template",
]
