"""Reference experiment: scalar DC bias crossed with a programmable AWG list."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace
from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_BIAS_TEMPLATE,
    FakeBiasVoltageProvider,
    FakeXCountDomainCompiler,
    fake_x_count_bias_config,
)

# %%
workspace = notebook_workspace("12-fake-awg-with-bias")
voltage_source = FakeBiasVoltageProvider()
compiler = FakeXCountDomainCompiler()
lab = sc.open(
    workspace,
    config_profile=fake_x_count_bias_config(),
    system=sc.ExperimentSystem(
        provider=voltage_source,
        domain_compiler=compiler,
    ),
)

# %%
experiment = lab.prepare(
    FAKE_X_COUNT_BIAS_TEMPLATE,
)
preview = experiment.preview()
completed_run = experiment.run(
    name="fake AWG X-count with scalar DC bias",
    tags=("reference", "fake-hardware", "mixed-execution"),
)
measurements = completed_run.data().measurements().dataset.records

# %%
bias_x_count_points = [
    (
        record.coordinates["bias_voltage"],
        record.coordinates["x_count"],
    )
    for record in measurements
]
bias_readbacks = [
    record.observables["bias_voltage_readback"] for record in measurements
]
mixed_execution_results = {
    "status": completed_run.manifest.status,
    "logical_points": preview.point_count,
    "record_ids": [record.id for record in preview.records],
    "voltage_writes": list(voltage_source.writes),
    "physical_awg_executions": compiler.runtime.physical_execution_count,
    "bias_x_count_points": bias_x_count_points,
    "bias_readbacks": bias_readbacks,
}
print(mixed_execution_results)
