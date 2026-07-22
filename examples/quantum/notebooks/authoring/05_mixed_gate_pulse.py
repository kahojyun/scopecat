"""Mix gates, pulse templates, frames, and acquisition in one program."""

from __future__ import annotations

# %%
from typing import Annotated

import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.virtual_lab.parameters import qubit_parameters
from quantum_lab_demo.workflows.ramsey_phase_experiment import (
    DEFAULT_PHASES,
    PHASE,
    RAMSEY_PHASE_EXPERIMENT_ID,
    ramsey_readout_pulse,
    ramsey_x90_candidate,
)
from scopecat_quantum import authoring as q

_X90 = q.single_qubit_gate("x90")
_RAMSEY_DELAY = sc.Quantity(16, "ns")
_READOUT_DURATION = sc.Quantity(24, "ns")


@q.program(id=RAMSEY_PHASE_EXPERIMENT_ID)
def ramsey_phase_program(
    qubit: q.Qubit,
    phase: Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="rad")),
    ],
) -> q.QuantumFragment:
    """Compose logical and pulse-level statements in one recursive sequence."""

    return q.sequence(
        _X90(qubit),
        q.delay(q.drive(qubit), _RAMSEY_DELAY),
        q.shift_phase(q.drive(qubit), phase),
        ramsey_x90_candidate(qubit),
        q.parallel(
            ramsey_readout_pulse(qubit),
            q.acquire(
                qubit,
                duration=_READOUT_DURATION,
                result="iq_shots",
            ),
        ),
    )


@sc.template
def ramsey_phase_template() -> sc.ExperimentBody:
    call = (
        ramsey_phase_program(qubit="q0", phase=PHASE)
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(1)
    )
    return (
        sc.experiment(call)
        .scan(PHASE, DEFAULT_PHASES)
        .record_product(call.results.iq_shots)
    )


# %%
print(ramsey_phase_program.describe())
print(ramsey_phase_program.draw())

# %%
lab = quantum_lab(workspace=notebook_workspace("authoring-mixed-gate-pulse"))
experiment = lab.prepare(ramsey_phase_template())
preview = experiment.preview()
run = experiment.run(
    name="Ramsey phase DSL",
    tags=("authoring", "gate-pulse", "frame"),
)

# %%
compiled_summary = {
    "program": ramsey_phase_program.id,
    "inputs": tuple(port.id for port in ramsey_phase_program.inputs),
    "results": tuple(port.id for port in ramsey_phase_program.results),
    "points": preview.point_count,
    "records": tuple(record.id for record in preview.records),
    "status": run.manifest.status,
}
print(compiled_summary)
