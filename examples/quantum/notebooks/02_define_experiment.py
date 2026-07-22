"""Notebook-style example: define an experiment and customize its scan."""

from __future__ import annotations

# %%
from typing import Annotated, cast

import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments.parameter_refs import qubit_param
from quantum_lab_demo.experiments.points import READOUT_FREQUENCY
from quantum_lab_demo.experiments.readout_modules import READOUT_MODULE

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))


# %%
@sc.template(
    id="notebook.readout_frequency",
    kind="readout_frequency",
    label="readout frequency",
)
def readout_frequency(
    qubit: Annotated[sc.Input[str], _QUBIT],
) -> sc.ExperimentBody:
    """Scan the readout frequency and keep the raw IQ product."""

    readout = READOUT_MODULE(qubit=qubit)
    return (
        sc.experiment(readout)
        .scan(
            READOUT_FREQUENCY,
            center=qubit_param("readout_frequency", cast("sc.ValueRef", qubit)),
            span=sc.Quantity(value=100.0, unit="MHz"),
            points=5,
        )
        .record_product(readout.products.raw_iq, record_id="raw_iq")
    )


# %%
workspace = notebook_workspace("02-define-experiment")
lab = quantum_lab(workspace=workspace)

# %%
qubit = "q0"
scan_points = 41
scan_span = sc.Quantity(value=60.0, unit="MHz")

preview = (
    lab.prepare(readout_frequency)
    .input("qubit", qubit)
    .scan(READOUT_FREQUENCY, span=scan_span, points=scan_points)
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
