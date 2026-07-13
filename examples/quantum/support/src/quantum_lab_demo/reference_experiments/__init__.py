"""Executable reference compositions for the demo laboratory.

These modules keep lab-owned quantum calibration and target wiring out of
notebooks without defining another Scopecat authoring or workspace API.
"""

from quantum_lab_demo.reference_experiments.fake_x_count import (
    FakeXCountProductBinding,
    PreparedFakeXCountReference,
    prepare_fake_x_count_reference,
)
from quantum_lab_demo.reference_experiments.fake_x_count_bias import (
    BIAS_CAPABILITY_ID,
    BIAS_SOURCE_ID,
    BIAS_VOLTAGE,
    DEFAULT_BIAS_VOLTAGES,
    FAKE_BIAS_SOURCE_MODULE,
    FAKE_X_COUNT_BIAS_TEMPLATE,
    FakeBiasVoltageProvider,
    fake_x_count_bias_config,
)
from quantum_lab_demo.reference_experiments.fake_x_count_experiment import (
    DEFAULT_X_COUNTS,
    FAKE_X_COUNT_ADAPTER_ID,
    FAKE_X_COUNT_CAPTURE_MODULE,
    FAKE_X_COUNT_EXPERIMENT_ID,
    FAKE_X_COUNT_SHOTS,
    FAKE_X_COUNT_TEMPLATE,
    FAKE_X_COUNT_TEMPLATE_ID,
    X_COUNT,
    FakeXCountDomainExecutionAdapter,
    fake_x_count_scratch_experiment,
)

__all__ = [
    "BIAS_CAPABILITY_ID",
    "BIAS_SOURCE_ID",
    "BIAS_VOLTAGE",
    "DEFAULT_BIAS_VOLTAGES",
    "DEFAULT_X_COUNTS",
    "FAKE_BIAS_SOURCE_MODULE",
    "FAKE_X_COUNT_ADAPTER_ID",
    "FAKE_X_COUNT_BIAS_TEMPLATE",
    "FAKE_X_COUNT_CAPTURE_MODULE",
    "FAKE_X_COUNT_EXPERIMENT_ID",
    "FAKE_X_COUNT_SHOTS",
    "FAKE_X_COUNT_TEMPLATE",
    "FAKE_X_COUNT_TEMPLATE_ID",
    "X_COUNT",
    "FakeBiasVoltageProvider",
    "FakeXCountDomainExecutionAdapter",
    "FakeXCountProductBinding",
    "PreparedFakeXCountReference",
    "fake_x_count_bias_config",
    "fake_x_count_scratch_experiment",
    "prepare_fake_x_count_reference",
]
