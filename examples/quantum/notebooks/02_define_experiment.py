"""Notebook-style example: define an experiment and customize its sweep."""

from __future__ import annotations

# %%
import scopecat.authoring as authoring
from quantum_lab_demo import notebook_workspace, readout_frequency_lab
from quantum_lab_demo.readout import frequency_calibration
from scopecat.models.parameter import Quantity

# %%
workspace = notebook_workspace("02-define-experiment")
lab = readout_frequency_lab(workspace=workspace)

# %%
qubit = "q0"
sweep_points = 41
sweep_span = Quantity(value=60.0, unit="MHz")

source = frequency_calibration(
    qubit=qubit,
    sweep=authoring.around(
        "readout_frequency",
        span=sweep_span,
        points=sweep_points,
    ),
)
experiment = lab.experiment("readout frequency", source=source)

# %%
summary = {
    "experiment": experiment.name,
    "template": source.template_id,
    "qubit": qubit,
    "sweep": f"{sweep_points} points over {sweep_span.value} {sweep_span.unit}",
}
print(summary)
