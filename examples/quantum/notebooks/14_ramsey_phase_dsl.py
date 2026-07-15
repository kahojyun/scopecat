"""Inspect the unified gate, PulseTemplate, frame, and acquire UX."""

from __future__ import annotations

# %%
import math

from quantum_lab_demo.reference_experiments import (
    RAMSEY_READOUT_PULSE_TEMPLATE,
    RAMSEY_X90_PULSE_TEMPLATE,
    prepare_ramsey_phase_scan,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListTargetCompiler,
    default_fake_list_target,
)
from scopecat import Quantity
from scopecat_quantum import (
    TargetCompilerId,
    compile_target,
    prepare_quantum_target_batch,
)

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
program, entries = prepare_ramsey_phase_scan(phases)

authoring_summary = {
    "program": program.id,
    "inputs": tuple(port.id for port in program.inputs),
    "results": tuple(port.id for port in program.results),
    "x90_template": RAMSEY_X90_PULSE_TEMPLATE.id,
    "readout_template": RAMSEY_READOUT_PULSE_TEMPLATE.id,
}
print(authoring_summary)

# %%
# Target compilation consumes only the scheduled concrete pulse IR.  Frame
# state begins at zero for every list entry, and the shift rotates only the
# candidate X90 samples that follow it.
target = default_fake_list_target()
compiler = FakeListTargetCompiler(
    TargetCompilerId("ramsey-phase-notebook.v1"),
    target,
)
batch = prepare_quantum_target_batch(
    entries,
    target_id=target.id,
    compiler_id=compiler.id,
    capability_fingerprint=target.capability_fingerprint,
    repetitions=1,
)
artifact = compile_target(compiler, batch.request).artifact

candidate_samples = tuple(
    next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == "awg.drive.0"
    ).samples[32]
    for entry in artifact.entries
)
compiled_summary = {
    "entry_count": len(artifact.entries),
    "candidate_first_samples": candidate_samples,
    "acquisition_slots": tuple(
        entry.acquisitions[0].slot_id.value for entry in artifact.entries
    ),
}
print(compiled_summary)
