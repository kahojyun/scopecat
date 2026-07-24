"""Notebook-style example: run an experiment with a candidate config."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_analysis,
    readout_frequency_template,
)

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

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
