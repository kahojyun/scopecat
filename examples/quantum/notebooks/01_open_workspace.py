"""Notebook-style example: open the demo lab workspace."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, readout_frequency_lab

# %%
workspace = notebook_workspace("01-open-workspace")
lab = readout_frequency_lab(workspace=workspace)

# %%
summary = {
    "workspace": lab.workspace,
    "run_count": len(lab.runs()),
}
print(summary)
