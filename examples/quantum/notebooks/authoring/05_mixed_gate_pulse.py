"""Place standard gates around a direct multi-channel pulse layout."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.interaction_tomography import (
    interaction_pulse_layout,
    interaction_tomography_program,
    interaction_tomography_template,
)

# State preparation and analysis use standard gates resolved from the accepted
# compiler parameters. The interaction remains an explicit pulse layout because
# a low-level characterization experiment need not claim stable gate semantics.
print(interaction_tomography_program.describe())
print(interaction_tomography_program.draw())

# %%
lab = quantum_lab(workspace=notebook_workspace("authoring-mixed-gate-pulse"))
experiment = lab.prepare(interaction_tomography_template())
preview = experiment.preview()
run = experiment.run(
    name="direct interaction tomography",
    tags=("authoring", "gate-pulse", "tomography"),
)

# %%
compiled_summary = {
    "program": interaction_tomography_program.id,
    "direct_pulse": interaction_pulse_layout.id,
    "inputs": tuple(port.id for port in interaction_tomography_program.inputs),
    "results": tuple(port.id for port in interaction_tomography_program.results),
    "scan_axes": preview.coordinate_ids,
    "points": preview.point_count,
    "records": tuple(record.id for record in preview.records),
    "status": run.manifest.status,
}
print(compiled_summary)
