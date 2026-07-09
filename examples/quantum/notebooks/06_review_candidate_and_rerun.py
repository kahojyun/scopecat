"""Notebook-style example: run a candidate config and review the comparison."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import (
    READOUT_TEMPLATE,
    ReadoutFrequencyAnalysisStep,
)

# %%
workspace = notebook_workspace("06-review-and-rerun")
lab = quantum_lab(workspace=workspace)

# %%
baseline = (
    lab.prepare(READOUT_TEMPLATE)
    .input("qubit", "q0")
    .run(
        name="readout frequency baseline",
        tags=("notebook", "calibration", "baseline"),
    )
)
analysis = baseline.analyze(ReadoutFrequencyAnalysisStep())
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
follow_up = (
    lab.prepare(READOUT_TEMPLATE, config=candidate)
    .input("qubit", "q0")
    .run(
        name="readout frequency follow-up",
        tags=("notebook", "calibration", "candidate"),
    )
)

# %%
comparison = lab.compare(baseline, follow_up, observable="raw_iq")
comparison_review = comparison.review(state="accepted")

# %%
change = analysis.parameter_changes[0]
summary = {
    "baseline": baseline.id,
    "parameter_change": change.id,
    "saved_analysis": saved_analysis.record.id,
    "candidate": candidate.analysis_key,
    "follow_up": follow_up.id,
    "comparison": comparison.id,
    "comparison_review": comparison_review.review.decision,
}
print(summary)
