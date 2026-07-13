"""Reference experiment: reusable Template on a fake list AWG and digitizer."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_TEMPLATE,
    FakeXCountDomainExecutionAdapter,
)

# %%
workspace = notebook_workspace("10-fake-awg-template")
adapter = FakeXCountDomainExecutionAdapter()
lab = quantum_lab(workspace=workspace)

# %%
experiment = lab.prepare(
    FAKE_X_COUNT_TEMPLATE,
    execution_backend=sc.DomainProgramBackend(adapter),
)
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
    "record_producers": {record.id: record.producer_kind for record in preview.records},
    "physical_executions": adapter.runtime.physical_execution_count,
    "measurement_count": len(measurements),
}
print(template_summary)
