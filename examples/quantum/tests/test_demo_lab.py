from __future__ import annotations

import runpy
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from quantum_lab_demo import (
    NOTEBOOK_WORKSPACE_ROOT_ENV,
)
from scopecat import Quantity, RunHandle

EXAMPLE_ROOT = Path(__file__).parents[1]
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"


def test_notebook_style_examples_execute_user_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(NOTEBOOK_WORKSPACE_ROOT_ENV, str(tmp_path))

    candidate_rerun = _run_notebook("06_rerun_candidate_config.py")
    gate_family = _run_notebook("07_gate_calibration_family.py")
    readout_family = _run_notebook("08_readout_family.py")
    system_scale = _run_notebook("09_system_scale_cases.py")
    fake_template = _run_notebook("10_fake_awg_template.py")
    fake_scratch = _run_notebook("11_fake_awg_scratch.py")
    fake_with_bias = _run_notebook("12_fake_awg_with_bias.py")
    drag_beta = _run_notebook("13_drag_beta_calibration.py")
    ramsey_phase = _run_notebook("14_ramsey_phase_dsl.py")
    cz_phase = _run_notebook("15_cz_conditional_phase.py")

    baseline = cast("RunHandle", candidate_rerun["baseline"])
    follow_up = cast("RunHandle", candidate_rerun["follow_up"])
    completed_run = cast("RunHandle", drag_beta["completed_run"])
    cz_run = cast("RunHandle", cz_phase["run"])

    assert baseline.manifest.status == "completed"
    assert follow_up.manifest.status == "completed"
    assert baseline.id != follow_up.id
    assert gate_family["gate_family_summary"] == {
        "rabi_points": 7,
        "rabi_qubit_scan_points": 10,
        "rabi_qubit_scan_coordinates": ["qubit", "drive_length"],
        "simultaneous_rabi_points": 5,
        "flux_background_records": ["probability_1", "raw_iq"],
        "system_background_records": ["probability_1", "raw_iq"],
        "cz_rb_points": 3,
        "cz_chevron_points": 4,
        "runtime_scan_points": 2,
        "runtime_scan_coordinates": [
            "coupler_duration",
            "coupler_amplitude",
            "parking_flux",
        ],
        "spectator_cz_points": 1,
        "parallel_gate_collection_size": 2,
        "parallel_gate_points": 1,
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
        "backend_batch_points": 1,
        "backend_batch_records": ["backend_probabilities"],
    }
    expected_fake_summary = {
        "status": "completed",
        "points": 4,
        "record_ids": ["probability_0", "probability_1"],
        "physical_executions": 1,
        "measurement_count": 4,
    }
    assert fake_template["template_summary"] == expected_fake_summary
    assert fake_scratch["scratch_summary"] == expected_fake_summary
    mixed_summary = cast("dict[str, object]", fake_with_bias["mixed_execution_results"])
    assert mixed_summary["status"] == "completed"
    assert mixed_summary["logical_points"] == 8
    assert mixed_summary["record_ids"] == [
        "probability_0",
        "probability_1",
        "bias_voltage_readback",
    ]
    assert mixed_summary["voltage_writes"] == [
        Quantity(value=-0.1, unit="V"),
        Quantity(value=0.1, unit="V"),
    ]
    assert 1 <= cast("int", mixed_summary["physical_awg_executions"]) <= 8
    assert mixed_summary["bias_readbacks"] == [
        point[0]
        for point in cast(
            "Sequence[Sequence[object]]", mixed_summary["bias_x_count_points"]
        )
    ]
    drag_summary = cast("dict[str, object]", drag_beta["drag_beta_summary"])
    assert drag_summary["status"] == "completed"
    assert drag_summary["point_count"] == 15
    assert drag_summary["physical_executions"] == 4
    beta_hat = cast("Quantity", drag_summary["beta_hat"])
    quality = cast("dict[str, object]", drag_summary["quality"])
    assert float(beta_hat.to("ns").value) == pytest.approx(0.765)
    assert quality["kind"] == "heuristic"
    assert quality["recommendation"] == "propose"
    assert 0.0 <= cast("float", quality["score"]) <= 1.0
    assert drag_summary["analysis_record_id"] == "analysis-drag-beta-calibration"
    assert drag_summary["proposal_id"] == "q0-drag-beta"
    assert drag_summary["review"] == "approved"
    assert drag_summary["registry_generations"] == {
        "baseline": 1,
        "candidate": 2,
        "rollback": 3,
    }
    assert drag_summary["candidate_preview_center_ns"] == pytest.approx(0.765)
    assert drag_summary["parameter_flow"] == {
        "stages": (
            "ParameterSnapshot",
            "parameter_lookup",
            "param_axis overlay",
            "QuantumLabCompiler input",
            "proposal",
            "active",
            "rollback",
        ),
        "source_snapshot_id": "templates-parameter-snapshot",
        "scan": {
            "table": "qubits",
            "row": {"qubit": "q0"},
            "column": "drag_beta",
            "center_ns": pytest.approx(0.5),
        },
        "compiler_input": {
            "program_input": "beta",
            "values_ns": pytest.approx((0.0, 0.25, 0.5, 0.75, 1.0)),
        },
        "proposal": {
            "id": "q0-drag-beta",
            "candidate_snapshot_id": "candidate-q0-drag-beta.parameters",
            "beta_ns": pytest.approx(0.765),
        },
        "active_snapshot_id": "candidate-q0-drag-beta.parameters",
        "rollback_snapshot_id": "templates-parameter-snapshot",
    }
    assert drag_summary["production_baseline"] == {
        "run_status": "completed",
        "run_config_entry_id": f"drag-beta-baseline-{completed_run.id}",
        "run_registry_generation": 1,
        "production_beta_ns": pytest.approx(0.5),
        "config_hash_matches": True,
    }
    assert drag_summary["active"] == {
        "entry_id": f"drag-beta-candidate-{completed_run.id}",
        "generation": 2,
        "run_status": "completed",
        "run_config_entry_id": f"drag-beta-candidate-{completed_run.id}",
        "run_registry_generation": 2,
        "scan_center_ns": pytest.approx(0.765),
        "production_beta_ns": pytest.approx(0.765),
        "production_waveform_changed": True,
        "trusted_reference_unchanged": True,
        "artifact_changed": True,
        "config_hash_matches": True,
    }
    assert drag_summary["rollback"] == {
        "generation": 3,
        "entry_id": f"drag-beta-baseline-{completed_run.id}",
        "run_status": "completed",
        "run_config_entry_id": f"drag-beta-baseline-{completed_run.id}",
        "run_registry_generation": 3,
        "scan_center_ns": pytest.approx(0.5),
        "production_beta_ns": pytest.approx(0.5),
        "production_waveform_restored": True,
        "artifact_restored": True,
        "config_hash_matches": True,
    }
    assert ramsey_phase["authoring_summary"] == {
        "program": "ramsey-phase-calibration",
        "inputs": ("phase",),
        "results": ("iq_shots",),
        "x90_template": "ramsey-phase.x90-candidate",
        "readout_template": "ramsey-phase.readout-stimulus",
    }
    ramsey_compiled = cast("dict[str, object]", ramsey_phase["compiled_summary"])
    assert ramsey_compiled == {
        "status": "completed",
        "entry_count": 3,
        "physical_executions": 1,
        "candidate_first_samples": pytest.approx(
            (complex(0.2, 0.0), complex(0.0, 0.2), complex(-0.2, 0.0))
        ),
        "acquisition_slots": ("iq_shots", "iq_shots", "iq_shots"),
    }
    cz_summary = cast("dict[str, dict[str, object]]", cz_phase["summary"])
    assert cz_summary["program"] == {
        "program": "cz-conditional-phase",
        "inputs": ("control_state", "coupler_amplitude", "analyzer_phase"),
        "results": ("control_iq_shots", "target_iq_shots"),
        "cz_template": "cz-phase.coupler-flux",
    }
    assert cz_summary["parameter_scan"] == {
        "snapshot_id": "templates-parameter-snapshot",
        "table": "two_qubit_gates",
        "row": {
            "control_qubit": "q0",
            "partner_qubit": "q1",
            "gate": "cz",
        },
        "column": "coupler_amplitude",
        "accepted_center": pytest.approx(0.2),
        "scanned_values": pytest.approx((0.16, 0.2, 0.24)),
    }
    assert cz_summary["measurement"] == {
        "run_id": cz_run.id,
        "status": "completed",
        "points": 24,
        "coordinates": (
            "coupler_amplitude",
            "control_state",
            "analyzer_phase",
        ),
        "records": 24,
        "observables": ("control_probability_1", "target_probability_1"),
        "physical_executions": 1,
    }
    physical = cz_summary["physical"]
    assert physical["candidate_events"] == 24
    assert physical["candidate_ids"] == ("cz.conditional-phase",)
    assert physical["candidate_gate_ids"] == ("cz",)
    assert physical["template_ids"] == ("cz-phase.coupler-flux",)
    assert physical["flux_channels"] == ("awg.flux.0",)
    assert cast("str", physical["artifact_fingerprint"]).startswith("sha256:")
    fit = cz_summary["fit"]
    assert fit["selected_amplitude"] == pytest.approx(0.24)
    assert fit["conditional_phase"] == pytest.approx(3.141592653589793)
    assert fit["phase_error"] == pytest.approx(0.0)
    assert cast("float", fit["minimum_contrast"]) > 0.85
    assert cast("float", fit["maximum_rmse"]) < 1e-12
    assert cast("float", fit["maximum_control_error"]) < 0.08
    assert fit["failed_checks"] == ()
    assert fit["proposal_id"] == "q0-q1-cz-coupler-amplitude"
    assert fit["candidate_amplitude"] == pytest.approx(0.24)
    assert fit["candidate_proposal_ids"] == ("q0-q1-cz-coupler-amplitude",)
    assert fit["analysis_record_id"] == "analysis-cz-conditional-phase"


def _run_notebook(name: str) -> dict[str, object]:
    namespace: object = runpy.run_path(str(NOTEBOOKS_DIR / name))
    return cast("dict[str, object]", namespace)
