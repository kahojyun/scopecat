"""Notebook-style example: run a candidate config and review the comparison."""

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
candidate = analysis.candidate_config(reason=analysis.parameter_changes[0].reason)
follow_up = lab.run(experiment, config=candidate)

# %%
comparison = lab.compare(baseline, follow_up, observable="raw_i")
comparison_review = comparison.review(state="accepted")

# %%
change = analysis.parameter_changes[0]
summary = {
    "baseline": baseline.id,
    "parameter_change": change.id,
    "saved_analysis": saved_analysis.artifact.id,
    "candidate": candidate.analysis_key,
    "follow_up": follow_up.id,
    "comparison": comparison.id,
    "comparison_review": comparison_review.review.decision,
}
print(summary)
