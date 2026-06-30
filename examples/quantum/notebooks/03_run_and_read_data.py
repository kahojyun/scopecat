"""Notebook-style example: open a workspace, run an experiment, read data."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, readout_frequency_lab
from quantum_lab_demo.readout import frequency_calibration

# %%
workspace = notebook_workspace("03-run-and-read-data")
lab = readout_frequency_lab(workspace=workspace)
experiment = lab.experiment(
    "readout frequency",
    source=frequency_calibration(qubit="q0"),
)

# %%
completed_run = lab.run(experiment)
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
