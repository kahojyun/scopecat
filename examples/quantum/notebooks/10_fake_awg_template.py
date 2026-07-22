"""Reference experiment: reusable Template on a fake list AWG and digitizer."""

from __future__ import annotations

# %%
from quantum_lab_demo import QuantumLabCompiler, notebook_workspace, quantum_lab
from quantum_lab_demo.reference_experiments import (
    fake_x_count_template,
)

# %%
workspace = notebook_workspace("10-fake-awg-template")
lab = quantum_lab(workspace=workspace)
system = lab.system
assert system is not None
compiler = system.domain_compiler
assert isinstance(compiler, QuantumLabCompiler)

# %%
experiment = lab.prepare(fake_x_count_template)
preview = experiment.preview()
completed_run = experiment.run(
    name="fake AWG X-count template",
    tags=("reference", "fake-hardware", "template"),
)
measurements = completed_run.data().measurements().dataset.records

# %%
template_summary = {
    "status": completed_run.manifest.status,
    "points": preview.point_count,
    "record_ids": [record.id for record in preview.records],
    "physical_executions": compiler.trace.physical_execution_count,
    "measurement_count": len(measurements),
}
print(template_summary)
