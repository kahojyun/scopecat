"""Notebook-style example: connect to a project, run an experiment, read data."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
completed_run = lab.prepare(readout_frequency_template(qubit="q0")).run()
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
