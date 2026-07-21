"""Stable identifiers for experiment-system experiment definitions."""

from __future__ import annotations

RABI_TEMPLATE_ID = "quantum_lab_demo.experiments.rabi"
SIMULTANEOUS_RABI_TEMPLATE_ID = "quantum_lab_demo.experiments.simultaneous_rabi"
FLUX_BACKGROUND_RABI_TEMPLATE_ID = "quantum_lab_demo.experiments.flux_background_rabi"
SYSTEM_BACKGROUND_RABI_TEMPLATE_ID = (
    "quantum_lab_demo.experiments.system_background_rabi"
)
READOUT_TEMPLATE_ID = "quantum_lab_demo.experiments.readout_frequency"
SQG_RB_TEMPLATE_ID = "quantum_lab_demo.experiments.sqg_rb"
CZ_RB_TEMPLATE_ID = "quantum_lab_demo.experiments.cz_rb"
CZ_CHEVRON_TEMPLATE_ID = "quantum_lab_demo.experiments.cz_chevron"
MULTIPLEXED_READOUT_TEMPLATE_ID = "quantum_lab_demo.experiments.multiplexed_readout"
MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID = (
    "quantum_lab_demo.experiments.multiplexed_readout_calibration"
)
SPECTATOR_CZ_TEMPLATE_ID = "quantum_lab_demo.experiments.spectator_cz_calibration"
PARALLEL_GATE_SET_TEMPLATE_ID = "quantum_lab_demo.experiments.parallel_gate_set"
TOY_SURFACE_CODE_ROUND_TEMPLATE_ID = (
    "quantum_lab_demo.experiments.toy_surface_code_round"
)
QND_REPEATED_MEASUREMENT_TEMPLATE_ID = (
    "quantum_lab_demo.experiments.qnd_repeated_measurement"
)
BACKEND_BATCH_TEMPLATE_ID = "quantum_lab_demo.experiments.backend_batch_out_of_order"

__all__ = [
    "BACKEND_BATCH_TEMPLATE_ID",
    "CZ_CHEVRON_TEMPLATE_ID",
    "CZ_RB_TEMPLATE_ID",
    "FLUX_BACKGROUND_RABI_TEMPLATE_ID",
    "MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID",
    "MULTIPLEXED_READOUT_TEMPLATE_ID",
    "PARALLEL_GATE_SET_TEMPLATE_ID",
    "QND_REPEATED_MEASUREMENT_TEMPLATE_ID",
    "RABI_TEMPLATE_ID",
    "READOUT_TEMPLATE_ID",
    "SIMULTANEOUS_RABI_TEMPLATE_ID",
    "SPECTATOR_CZ_TEMPLATE_ID",
    "SQG_RB_TEMPLATE_ID",
    "SYSTEM_BACKGROUND_RABI_TEMPLATE_ID",
    "TOY_SURFACE_CODE_ROUND_TEMPLATE_ID",
]
