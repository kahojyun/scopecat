"""Notebook-style example: define an experiment and customize its scan."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import READOUT_TEMPLATE

# %%
workspace = notebook_workspace("02-define-experiment")
lab = quantum_lab(workspace=workspace)

# %%
qubit = "q0"
scan_points = 41
scan_span = sc.Quantity(value=60.0, unit="MHz")

preview = (
    lab.prepare(READOUT_TEMPLATE)
    .input("qubit", qubit)
    .scan("readout_frequency", span=scan_span, points=scan_points)
    .preview(
        name="readout frequency",
        tags=("notebook", "calibration"),
        description="narrow scan selected interactively in the notebook",
    )
)

# %%
summary = {
    "experiment": preview.experiment_id,
    "qubit": qubit,
    "planned_points": preview.point_count,
    "scan": f"{scan_points} points over {scan_span.value} {scan_span.unit}",
}
print(summary)
