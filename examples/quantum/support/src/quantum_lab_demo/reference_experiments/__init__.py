"""Notebook-facing reference experiments for the demo quantum laboratory."""

from quantum_lab_demo.reference_experiments.cz_phase_analysis import (
    analyze_cz_phase_run,
)
from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    CZ_CANDIDATE_ID,
    CZ_FLUX_PULSE_TEMPLATE,
    cz_conditional_phase,
)
from quantum_lab_demo.reference_experiments.cz_phase_experiment import (
    CZ_AMPLITUDE,
    CZ_AMPLITUDE_POINTS,
    CZ_AMPLITUDE_SPAN,
    cz_phase_template,
)
from quantum_lab_demo.reference_experiments.drag_beta_analysis import (
    analyze_drag_beta_run,
)
from quantum_lab_demo.reference_experiments.drag_beta_experiment import (
    BETA,
    DRAG_BETA_POINTS,
    DRAG_BETA_SPAN,
    drag_beta_program,
    drag_beta_template,
)
from quantum_lab_demo.reference_experiments.fake_x_count_bias import (
    FakeBiasVoltageProvider,
    fake_x_count_bias_config,
    fake_x_count_bias_template,
)
from quantum_lab_demo.reference_experiments.fake_x_count_experiment import (
    X_COUNT,
    fake_x_count_capture,
    fake_x_count_scratch_experiment,
    fake_x_count_template,
    x_count_program,
)
from quantum_lab_demo.reference_experiments.production_drag_gate import (
    production_drag_program,
    production_drag_template,
)
from quantum_lab_demo.reference_experiments.ramsey_phase_experiment import (
    PHASE,
    RAMSEY_READOUT_PULSE_TEMPLATE,
    RAMSEY_X90_PULSE_TEMPLATE,
    ramsey_phase_program,
    ramsey_phase_template,
)
from quantum_lab_demo.reference_experiments.single_qubit_rb import (
    CLIFFORD_LENGTH,
    RB_SEED,
    SINGLE_QUBIT_RB_TEMPLATE_ID,
    randomized_clifford_sequence,
    single_qubit_rb_program,
    single_qubit_rb_scratch,
    single_qubit_rb_template,
)

__all__ = [
    "BETA",
    "CLIFFORD_LENGTH",
    "CZ_AMPLITUDE",
    "CZ_AMPLITUDE_POINTS",
    "CZ_AMPLITUDE_SPAN",
    "CZ_CANDIDATE_ID",
    "CZ_FLUX_PULSE_TEMPLATE",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SPAN",
    "PHASE",
    "RAMSEY_READOUT_PULSE_TEMPLATE",
    "RAMSEY_X90_PULSE_TEMPLATE",
    "RB_SEED",
    "SINGLE_QUBIT_RB_TEMPLATE_ID",
    "X_COUNT",
    "FakeBiasVoltageProvider",
    "analyze_cz_phase_run",
    "analyze_drag_beta_run",
    "cz_conditional_phase",
    "cz_phase_template",
    "drag_beta_program",
    "drag_beta_template",
    "fake_x_count_bias_config",
    "fake_x_count_bias_template",
    "fake_x_count_capture",
    "fake_x_count_scratch_experiment",
    "fake_x_count_template",
    "production_drag_program",
    "production_drag_template",
    "ramsey_phase_program",
    "ramsey_phase_template",
    "randomized_clifford_sequence",
    "single_qubit_rb_program",
    "single_qubit_rb_scratch",
    "single_qubit_rb_template",
    "x_count_program",
]
