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
candidate = analysis.candidate_config(reason=analysis.parameter_proposals[0].reason)
overview = completed_run.overview()

# %%
proposal = candidate.proposals[0]
summary = {
    "run": completed_run.id,
    "analysis": saved_analysis.artifact.id,
    "overview_lines": len(overview.markdown.splitlines()),
    "candidate_proposal": proposal.parameter_id,
}
print(summary)
