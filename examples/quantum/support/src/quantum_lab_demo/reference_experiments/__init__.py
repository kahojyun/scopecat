"""Notebook-facing reference experiments for the demo quantum laboratory."""

from quantum_lab_demo.reference_experiments.cz_phase_analysis import (
    analyze_cz_phase_run,
)
from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    CZ_CANDIDATE_ID,
    CZ_FLUX_PULSE_TEMPLATE,
    cz_conditional_phase_program,
)
from quantum_lab_demo.reference_experiments.cz_phase_experiment import (
    CZ_AMPLITUDE,
    CZ_AMPLITUDE_POINTS,
    CZ_AMPLITUDE_SPAN,
    CZ_PHASE_TEMPLATE,
)
from quantum_lab_demo.reference_experiments.drag_beta_analysis import (
    analyze_drag_beta_run,
)
from quantum_lab_demo.reference_experiments.drag_beta_experiment import (
    BETA,
    DRAG_BETA_POINTS,
    DRAG_BETA_SPAN,
    DRAG_BETA_TEMPLATE,
)
from quantum_lab_demo.reference_experiments.fake_x_count_bias import (
    FAKE_X_COUNT_BIAS_TEMPLATE,
    FakeBiasVoltageProvider,
    fake_x_count_bias_config,
)
from quantum_lab_demo.reference_experiments.fake_x_count_experiment import (
    FAKE_X_COUNT_CAPTURE_MODULE,
    FAKE_X_COUNT_TEMPLATE,
    X_COUNT,
    fake_x_count_domain_execution,
    fake_x_count_scratch_experiment,
)
from quantum_lab_demo.reference_experiments.production_drag_gate import (
    PRODUCTION_DRAG_GATE_TEMPLATE,
)
from quantum_lab_demo.reference_experiments.ramsey_phase_experiment import (
    PHASE,
    RAMSEY_PHASE_PROGRAM,
    RAMSEY_PHASE_TEMPLATE,
    RAMSEY_READOUT_PULSE_TEMPLATE,
    RAMSEY_X90_PULSE_TEMPLATE,
)

__all__ = [
    "BETA",
    "CZ_AMPLITUDE",
    "CZ_AMPLITUDE_POINTS",
    "CZ_AMPLITUDE_SPAN",
    "CZ_CANDIDATE_ID",
    "CZ_FLUX_PULSE_TEMPLATE",
    "CZ_PHASE_TEMPLATE",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE",
    "FAKE_X_COUNT_BIAS_TEMPLATE",
    "FAKE_X_COUNT_CAPTURE_MODULE",
    "FAKE_X_COUNT_TEMPLATE",
    "PHASE",
    "PRODUCTION_DRAG_GATE_TEMPLATE",
    "RAMSEY_PHASE_PROGRAM",
    "RAMSEY_PHASE_TEMPLATE",
    "RAMSEY_READOUT_PULSE_TEMPLATE",
    "RAMSEY_X90_PULSE_TEMPLATE",
    "X_COUNT",
    "FakeBiasVoltageProvider",
    "analyze_cz_phase_run",
    "analyze_drag_beta_run",
    "cz_conditional_phase_program",
    "fake_x_count_bias_config",
    "fake_x_count_domain_execution",
    "fake_x_count_scratch_experiment",
]
