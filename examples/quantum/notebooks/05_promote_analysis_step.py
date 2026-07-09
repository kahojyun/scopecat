"""Notebook-style example: replace manual analysis with a reusable AnalysisStep."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import (
    READOUT_TEMPLATE,
    ReadoutFrequencyAnalysisStep,
)

# %%
workspace = notebook_workspace("05-promoted-analysis")
lab = quantum_lab(workspace=workspace)

# %%
completed_run = (
    lab.prepare(READOUT_TEMPLATE)
    .input("qubit", "q0")
    .run(
        name="readout frequency",
        tags=("notebook", "calibration"),
    )
)
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
