"""Notebook-style example: define an experiment and customize its sweep."""

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
sweep_points = 41
sweep_span = sc.Quantity(value=60.0, unit="MHz")

preview = lab.preview(
    READOUT_TEMPLATE,
    inputs={
        "qubit": qubit,
        "readout_frequency": sc.around(
            "readout_frequency",
            span=sweep_span,
            points=sweep_points,
        ),
    },
    name="readout frequency",
    tags=("notebook", "calibration"),
    description="narrow sweep selected interactively in the notebook",
)

# %%
summary = {
    "experiment": preview.experiment_id,
    "qubit": qubit,
    "planned_points": preview.point_count,
    "sweep": f"{sweep_points} points over {sweep_span.value} {sweep_span.unit}",
}
print(summary)
