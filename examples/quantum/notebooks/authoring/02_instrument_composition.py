"""Compose scalar DC bias with a programmable AWG list."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import (
    EXAMPLE_ROOT,
    quantum_lab_compiler,
)
from quantum_lab_demo.workflows.fake_x_count_bias import (
    FakeBiasVoltageProvider,
    fake_x_count_bias_config,
    fake_x_count_bias_template,
)

# %%
voltage_source = FakeBiasVoltageProvider()
project = sc.open_project(EXAMPLE_ROOT)
lab = project.connect(
    build_system=lambda _config: sc.ExperimentSystem(
        provider=voltage_source, domain_compiler=quantum_lab_compiler()
    ),
)

# %%
experiment = lab.prepare(
    fake_x_count_bias_template(),
    config=fake_x_count_bias_config(),
)
preview = experiment.preview()
completed_run = experiment.run()
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
    "bias_x_count_points": bias_x_count_points,
    "bias_readbacks": bias_readbacks,
}
print(mixed_execution_results)
