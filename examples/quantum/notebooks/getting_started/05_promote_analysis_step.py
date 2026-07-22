"""Replace manual analysis with a reusable function-authored analysis step."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_analysis,
    readout_frequency_template,
)

# %%
workspace = notebook_workspace("05-promoted-analysis")
lab = quantum_lab(workspace=workspace)

# %%
completed_run = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency",
    tags=("notebook", "calibration"),
)
analysis = completed_run.analyze(readout_frequency_analysis(qubit="q0"))
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()

# %%
delta = candidate.parameter_proposals[0].deltas[0]
summary = {
    "run": completed_run.id,
    "analysis": saved_analysis.record.id,
    "run_artifacts": len(completed_run.artifacts),
    "candidate_parameter_change": delta.parameter_id,
}
print(summary)
