"""Notebook-style example: define an experiment and customize its scan."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import (
    READOUT_FREQUENCY,
    readout_module,
)
from scopecat_quantum import authoring as q


# %%
@sc.template
def readout_frequency(
    qubit: q.QubitInput,
) -> sc.ExperimentBody:
    """Scan the readout frequency and keep the raw IQ product."""

    readout = readout_module(qubit=qubit)
    return (
        sc.experiment(readout)
        .scan(
            READOUT_FREQUENCY,
            center=sc.Quantity(value=5.95, unit="GHz"),
            span=sc.Quantity(value=100.0, unit="MHz"),
            points=5,
        )
        .record_product(readout.products.raw_iq)
    )


# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
qubit = "q0"
scan_points = 41
scan_span = sc.Quantity(value=60.0, unit="MHz")

preview = (
    lab.prepare(readout_frequency(qubit=qubit))
    .scan(READOUT_FREQUENCY, span=scan_span, points=scan_points)
    .preview()
)

# %%
summary = {
    "experiment": preview.experiment_id,
    "qubit": qubit,
    "planned_points": preview.point_count,
    "scan": f"{scan_points} points over {scan_span.value} {scan_span.unit}",
}
print(summary)
