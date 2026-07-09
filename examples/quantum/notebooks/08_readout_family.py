"""Notebook-style example: readout experiment family."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import (
    MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE,
    MULTIPLEXED_READOUT_TEMPLATE,
    QND_REPEATED_MEASUREMENT_TEMPLATE,
    READOUT_TEMPLATE,
)

# %%
workspace = notebook_workspace("08-readout-family")
lab = quantum_lab(workspace=workspace)

# %%
single_readout_preview = (
    lab.prepare(READOUT_TEMPLATE)
    .input("qubit", "q0")
    .scan("readout_frequency", span=sc.Quantity(value=80.0, unit="MHz"), points=5)
    .preview(
        name="readout family single-qubit frequency scan",
        tags=("readout", "frequency"),
        description="single-qubit readout frequency scan with dense complex IQ records",
    )
)

# %%
multiplexed_preview = lab.prepare(MULTIPLEXED_READOUT_TEMPLATE).preview(
    name="readout family multiplexed readout",
    tags=("readout", "multiplexed"),
    description="one logical point returning a complex array over the qubit axis",
)

# %%
multiplexed_calibration_preview = (
    lab.prepare(MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE)
    .scan("readout_frequency", span=sc.Quantity(value=80.0, unit="MHz"), points=5)
    .preview(
        name="readout family multiplexed calibration",
        tags=("readout", "multiplexed", "calibration"),
        description="shared readout pulse scan returning an entity-axis array",
    )
)

# %%
qnd_preview = (
    lab.prepare(QND_REPEATED_MEASUREMENT_TEMPLATE)
    .inputs(
        qubit="q0",
        rounds=sc.Quantity(value=3.0, unit="count"),
        shots=sc.Quantity(value=5.0, unit="count"),
    )
    .preview(
        name="readout family QND repeated measurement",
        tags=("readout", "qnd"),
        description="single logical point returning a dense round-by-shot IQ array",
    )
)

# %%
readout_family_summary = {
    "single_readout_points": single_readout_preview.point_count,
    "single_readout_records": [record.id for record in single_readout_preview.records],
    "multiplexed_records": [record.id for record in multiplexed_preview.records],
    "multiplexed_coordinates": list(multiplexed_preview.coordinate_ids),
    "multiplexed_calibration_points": multiplexed_calibration_preview.point_count,
    "multiplexed_calibration_coordinates": list(
        multiplexed_calibration_preview.coordinate_ids
    ),
    "qnd_records": [record.id for record in qnd_preview.records],
}
print(readout_family_summary)
