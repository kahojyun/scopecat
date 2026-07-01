"""Notebook-style example: review a candidate config and rerun."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, readout_frequency_lab
from quantum_lab_demo.readout import (
    ReadoutFrequencyAnalysisStep,
    frequency_calibration,
)

# %%
workspace = notebook_workspace("06-review-and-rerun")
lab = readout_frequency_lab(workspace=workspace)
experiment = lab.experiment(
    "readout frequency",
    source=frequency_calibration(qubit="q0"),
)

# %%
baseline = lab.run(experiment)
analysis = baseline.analyze(ReadoutFrequencyAnalysisStep())
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config(reason=analysis.parameter_proposals[0].reason)
review = lab.review(candidate, note="accept promoted readout analysis")
follow_up = lab.run(experiment, config=review)

# %%
comparison = lab.compare(baseline, follow_up, observable="raw_i")

# %%
proposal = analysis.parameter_proposals[0]
summary = {
    "baseline": baseline.id,
    "accepted_proposal": proposal.parameter_id,
    "saved_analysis": saved_analysis.artifact.id,
    "candidate": review.candidate_config_artifact.id,
    "follow_up": follow_up.id,
    "comparison": comparison.id,
}
print(summary)
