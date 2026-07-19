"""Reference experiment: scratch Experiment on the same fake quantum target."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.reference_experiments import (
    FakeXCountDomainCompiler,
    fake_x_count_scratch_experiment,
)

# %%
workspace = notebook_workspace("11-fake-awg-scratch")
lab = quantum_lab(workspace=workspace)
backend = lab.execution_backend
assert backend is not None
adapter = next(
    item
    for item in backend.domain_compilers
    if isinstance(item, FakeXCountDomainCompiler)
)

# %%
experiment = lab.prepare(
    fake_x_count_scratch_experiment(
        lab,
        x_counts=(0, 1, 3, 5),
    ),
)
preview = experiment.preview()
completed_run = experiment.run(
    name="fake AWG X-count scratch",
    tags=("reference", "fake-hardware", "scratch"),
)
measurements = completed_run.data().measurements().dataset.records

# %%
scratch_summary = {
    "status": completed_run.manifest.status,
    "points": preview.point_count,
    "record_ids": [record.id for record in preview.records],
    "physical_executions": adapter.runtime.physical_execution_count,
    "measurement_count": len(measurements),
}
print(scratch_summary)
