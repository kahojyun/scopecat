"""Notebook-style example: run an experiment with a candidate config."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_analysis,
    readout_frequency_template,
)

# %%
workspace = notebook_workspace("06-rerun-candidate-config")
lab = quantum_lab(workspace=workspace)

# %%
baseline = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency baseline",
    tags=("notebook", "calibration", "baseline"),
)
analysis = baseline.analyze(readout_frequency_analysis(qubit="q0"))
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
follow_up = lab.prepare(readout_frequency_template(qubit="q0"), config=candidate).run(
    name="readout frequency follow-up",
    tags=("notebook", "calibration", "candidate"),
)

# %%
proposal = analysis.parameter_proposals[0]
summary = {
    "baseline": baseline.id,
    "parameter_change": proposal.id,
    "saved_analysis": saved_analysis.record.id,
    "candidate_proposals": candidate.proposal_ids,
    "follow_up": follow_up.id,
}
print(summary)
