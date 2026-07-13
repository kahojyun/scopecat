from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

from quantum_lab_demo import (
    NOTEBOOK_WORKSPACE_ROOT_ENV,
)

EXAMPLE_ROOT = Path(__file__).parents[1]
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"


def test_notebook_style_examples_execute_user_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(NOTEBOOK_WORKSPACE_ROOT_ENV, str(tmp_path))

    review_rerun = _run_notebook("06_review_candidate_and_rerun.py")
    gate_family = _run_notebook("07_gate_calibration_family.py")
    readout_family = _run_notebook("08_readout_family.py")
    system_scale = _run_notebook("09_system_scale_cases.py")
    fake_template = _run_notebook("10_fake_awg_template.py")
    fake_scratch = _run_notebook("11_fake_awg_scratch.py")

    assert review_rerun["baseline"].manifest.status == "completed"
    assert review_rerun["follow_up"].manifest.status == "completed"
    assert (
        review_rerun["comparison"].result.baseline_run_id == review_rerun["baseline"].id
    )
    assert (
        review_rerun["comparison"].result.candidate_run_id
        == review_rerun["follow_up"].id
    )
    assert gate_family["gate_family_summary"] == {
        "rabi_points": 7,
        "rabi_qubit_scan_points": 10,
        "rabi_qubit_scan_coordinates": ["qubit", "drive_length"],
        "simultaneous_rabi_points": 5,
        "flux_background_state_count": 1,
        "system_background_state_channels": [
            (
                "coupler-stack",
                "set_flux_bias",
                "offset",
                [("coupler-q0-q1", "coupler.bias0")],
            ),
            (
                "coupler-stack",
                "set_flux_bias",
                "offset",
                [("coupler-q2-q3", "coupler.bias1")],
            ),
        ],
        "cz_rb_points": 3,
        "cz_chevron_points": 4,
        "runtime_scan_points": 2,
        "runtime_scan_coordinates": [
            "coupler_duration",
            "coupler_amplitude",
            "parking_flux",
        ],
        "spectator_cz_points": 1,
        "parallel_gate_points": 1,
        "waveform_preview_payloads": [
            (
                "cz_chevron/build-cz-chevron-program",
                "gate_sequence",
                (("play_gate_sequence", "sequence"),),
            ),
            (
                "cz_chevron/render-cz-chevron-coupler-waveforms",
                "pulse_program",
                (("play_coupler_pulse", "program"),),
            ),
            (
                "cz_chevron/render-cz-chevron-drive-waveforms",
                "pulse_program",
                (("play_pulse_program", "program"),),
            ),
        ],
        "waveform_build_dependencies": {
            "input_refs": ("control_qubit", "coupler", "partner_qubit"),
            "parameters": ("qubits", "two_qubit_gates"),
            "point_columns": ("coupler_amplitude", "coupler_duration"),
        },
        "waveform_drive_runtime_dependencies": {
            "input_refs": ["control_qubit", "coupler", "partner_qubit"],
            "parameters": ["qubits", "two_qubit_gates"],
            "point_columns": ["coupler_amplitude", "coupler_duration"],
            "routes": ["cz_chevron/drive"],
            "upstream_compute": ["cz_chevron/build-cz-chevron-program"],
        },
        "waveform_run_status": "completed",
        "waveform_compute_event_count": 3,
        "waveform_shapes": [[24], [2, 24]],
        "waveform_channels": [1, 2],
    }
    assert readout_family["readout_family_summary"] == {
        "single_readout_points": 5,
        "single_readout_records": [
            "raw_iq",
            "state0_iq",
            "state1_iq",
            "state0_iq_stdev",
            "state1_iq_stdev",
        ],
        "multiplexed_records": ["multiplexed_iq"],
        "multiplexed_coordinates": [],
        "multiplexed_calibration_points": 5,
        "multiplexed_calibration_coordinates": ["readout_frequency"],
        "qnd_records": ["qnd_iq"],
    }
    assert system_scale["system_scale_summary"] == {
        "surface_code_records": ["stabilizer_iq"],
        "surface_code_coordinates": [],
        "backend_batch_payloads": ["batch/build-backend-batch-job"],
        "backend_batch_records": ["backend_probabilities"],
    }
    expected_fake_summary = {
        "status": "completed",
        "points": 4,
        "record_producers": {
            "integrated_iq_shots": "domain",
            "probability_0": "host_transform",
            "probability_1": "host_transform",
        },
        "physical_executions": 1,
        "measurement_count": 4,
    }
    assert fake_template["template_summary"] == expected_fake_summary
    assert fake_scratch["scratch_summary"] == expected_fake_summary


def _run_notebook(name: str) -> dict[str, Any]:
    return runpy.run_path(str(NOTEBOOKS_DIR / name))
