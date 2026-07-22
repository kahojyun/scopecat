"""Notebook-style example: open a workspace, run an experiment, read data."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template

# %%
workspace = notebook_workspace("03-run-and-read-data")
lab = quantum_lab(workspace=workspace)

# %%
completed_run = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency",
    tags=("notebook", "calibration"),
)
data = completed_run.data()

# %%
raw = data.measurements()
artifacts = data.list()

# %%
summary = {
    "run": completed_run.id,
    "status": completed_run.manifest.status,
    "measurements": len(raw.dataset.records),
    "artifacts": [artifact.id for artifact in artifacts],
}
print(summary)
