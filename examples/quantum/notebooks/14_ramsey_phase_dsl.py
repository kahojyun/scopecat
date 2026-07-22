"""Inspect the unified gate, PulseTemplate, frame, and acquire UX."""

from __future__ import annotations

# %%
import math

from quantum_lab_demo import (
    QuantumLabCompiler,
    notebook_workspace,
    quantum_lab,
)
from quantum_lab_demo.reference_experiments import (
    PHASE,
    RAMSEY_READOUT_PULSE_TEMPLATE,
    RAMSEY_X90_PULSE_TEMPLATE,
    ramsey_phase_program,
    ramsey_phase_template,
)
from scopecat import Quantity

# %%
# The declaration behind this scan is one Program:
#
# calibrated X90 gate
# -> drive delay
# -> shift_phase(drive(q0), phase)
# -> PulseTemplate-backed X90 candidate
# -> parallel(readout PulseTemplate, explicit acquire)
#
# ``phase`` is the only scan input, while the physical acquisition exposes the
# same first-class MeasurementResult contract as a logical measurement.
phases = tuple(Quantity(value, "rad") for value in (0, math.pi / 2, math.pi))

authoring_summary = {
    "program": ramsey_phase_program.id,
    "inputs": tuple(port.id for port in ramsey_phase_program.inputs),
    "results": tuple(port.id for port in ramsey_phase_program.results),
    "x90_template": RAMSEY_X90_PULSE_TEMPLATE.id,
    "readout_template": RAMSEY_READOUT_PULSE_TEMPLATE.id,
}
print(authoring_summary)

# %%
# The same Workspace path used by every other quantum example resolves phase
# values, lowers the Program, and runs the resulting list. Frame state begins at
# zero for every point, so the shift rotates only the candidate X90 that follows.
lab = quantum_lab(workspace=notebook_workspace("14-ramsey-phase-dsl"))
system = lab.system
assert system is not None
compiler = system.domain_compiler
assert isinstance(compiler, QuantumLabCompiler)
run = (
    lab.prepare(ramsey_phase_template)
    .scan(PHASE, phases)
    .run(
        name="Ramsey phase DSL",
        tags=("reference", "gate-pulse", "frame"),
    )
)
[preparation] = compiler.trace.preparations(ramsey_phase_program.id)
artifact = preparation.artifact

candidate_samples = tuple(
    next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == "awg.drive.0"
    ).samples[32]
    for entry in artifact.entries
)
compiled_summary = {
    "status": run.manifest.status,
    "entry_count": len(artifact.entries),
    "physical_executions": compiler.trace.physical_execution_count,
    "candidate_first_samples": candidate_samples,
    "acquisition_slots": tuple(
        entry.acquisitions[0].slot_id.value for entry in artifact.entries
    ),
}
print(compiled_summary)
