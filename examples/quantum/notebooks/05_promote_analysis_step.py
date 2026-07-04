"""Notebook-style example: replace manual analysis with a reusable AnalysisStep."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, readout_frequency_lab
from quantum_lab_demo.readout import (
    ReadoutFrequencyAnalysisStep,
    frequency_calibration,
)

# %%
workspace = notebook_workspace("05-promoted-analysis")
lab = readout_frequency_lab(workspace=workspace)
experiment = lab.experiment(
    "readout frequency",
    source=frequency_calibration(qubit="q0"),
)

# %%
completed_run = lab.run(experiment)
analysis = completed_run.analyze(ReadoutFrequencyAnalysisStep())
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
overview = completed_run.overview()

# %%
patch = candidate.parameter_changes[0].patches[0]
summary = {
    "run": completed_run.id,
    "analysis": saved_analysis.record.id,
    "run_artifacts": len(completed_run.artifacts),
    "candidate_parameter_change": patch.parameter_id,
}
print(summary)
