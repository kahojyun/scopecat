from __future__ import annotations

from pathlib import Path
from runpy import run_path
from typing import Protocol, cast


class _ReferenceLabDaemon(Protocol):
    url: str


NOTEBOOKS = Path(__file__).parents[1] / "notebooks"


def test_lab_tour_shows_one_inventory_and_parameter_catalog(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "00_lab_tour.py"))
    summary = cast("dict[str, object]", namespace["lab_tour_summary"])

    assert set(cast("list[str]", summary["instruments"])) == {
        "drive-stack",
        "readout-stack",
        "pump-source",
        "bench-source",
        "flux-dac-a",
        "flux-dac-b",
        "mixing-chamber",
        "readout-vna",
        "event-digitizer",
    }
    assert summary["parameter_rows"] == {
        "qubits": 4,
        "readout_resonators": 4,
        "channel_calibrations": 4,
        "bias_profiles": 8,
    }


def test_scan_shapes_run_as_real_lab_experiments(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "21_scan_shapes.py"))
    summary = cast("dict[str, object]", namespace["scan_shapes_summary"])

    assert summary == {
        "point_cloud_points": 4,
        "point_cloud_layout": "point_cloud",
        "point_cloud_rows": 4,
        "repeated_grid_points": 8,
        "repeated_grid_layout": "product_grid",
        "repeated_grid_rows": 8,
    }


def test_channel_map_exposes_independent_drive_and_demod_routes(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "22_channel_map.py"))
    summary = cast("dict[str, object]", namespace["channel_map_summary"])

    assert summary == {
        "drive": {
            "q0": "drive.awg0.ch1",
            "q1": "drive.awg0.ch2",
            "q2": "drive.awg0.ch3",
            "q3": "drive.awg0.ch4",
        },
        "readout": {
            "q0": "readout.mux0",
            "q1": "readout.mux0",
            "q2": "readout.mux0",
            "q3": "readout.mux0",
        },
        "acquisition": {
            "q0": "digitizer.demod0",
            "q1": "digitizer.demod1",
            "q2": "digitizer.demod2",
            "q3": "digitizer.demod3",
        },
        "flux": {
            "q0": ("flux-dac-a", "flux.dac_a.ch1"),
            "q1": ("flux-dac-a", "flux.dac_a.ch2"),
            "q2": ("flux-dac-b", "flux.dac_b.ch1"),
            "q3": ("flux-dac-b", "flux.dac_b.ch2"),
        },
    }


def test_multichannel_dc_bias_spans_two_devices_and_four_routes(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "33_multichannel_dc_bias.py"))
    summary = cast("dict[str, object]", namespace["multichannel_dc_bias_summary"])

    assert summary == {
        "devices": ["flux-dac-a", "flux-dac-b"],
        "routes": {
            "q0": ("flux-dac-a", "flux.dac_a.ch1"),
            "q1": ("flux-dac-a", "flux.dac_a.ch2"),
            "q2": ("flux-dac-b", "flux.dac_b.ch1"),
            "q3": ("flux-dac-b", "flux.dac_b.ch2"),
        },
        "profile": "operate",
        "physical_bias_mv": {
            "q0": -78.4,
            "q1": 22.4,
            "q2": 39.4,
            "q3": -96.0,
        },
        "readback_mv": {
            "q0": -78.4,
            "q1": 22.4,
            "q2": 39.4,
            "q3": -96.0,
        },
        "settled": {"q0": True, "q1": True, "q2": True, "q3": True},
        "records": 1,
        "status": "completed",
    }


def test_q0_ramsey_runs_on_the_reference_channels(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "23_q0_ramsey.py"))
    summary = cast("dict[str, object]", namespace["q0_ramsey_summary"])

    assert summary == {
        "points": 5,
        "records": 5,
        "probability_samples": 5,
        "status": "completed",
    }


def test_flux_ramsey_composes_local_bias_and_quantum_channels(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "24_flux_ramsey.py"))
    summary = cast("dict[str, object]", namespace["flux_ramsey_summary"])

    assert summary["points"] == 15
    assert summary["records"] == 15
    assert summary["status"] == "completed"
    assert sorted(cast("dict[str, int]", summary["dimensions"]).values()) == [3, 5]


def test_entity_routed_ramsey_switches_channel_sets_by_point(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "25_entity_routed_ramsey.py"))
    summary = cast("dict[str, object]", namespace["entity_ramsey_summary"])

    assert summary == {
        "points": 6,
        "records": 6,
        "qubit_groups": 2,
        "status": "completed",
    }


def test_parallel_ramsey_uses_two_drive_and_demod_channels(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "26_parallel_multiplexed_ramsey.py"))
    summary = cast("dict[str, object]", namespace["parallel_ramsey_summary"])

    assert summary == {
        "points": 3,
        "records": 3,
        "q0_samples": 3,
        "q1_samples": 3,
        "status": "completed",
    }


def test_channel_timing_candidate_preserves_analysis_provenance(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "27_channel_timing_candidate.py"))
    summary = cast("dict[str, object]", namespace["channel_candidate_summary"])

    assert summary["proposal_id"] == "q1-channel-delay"
    assert summary["candidate_status"] == "completed"
    assert summary["candidate_provenance"] is True


def test_channel_conflict_names_the_logical_drive_route(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "28_channel_conflict_diagnostic.py"))
    summary = cast("dict[str, object]", namespace["channel_conflict_summary"])

    assert "pulse_signal_overlap" in cast("list[str]", summary["codes"])
    assert summary["mentions_drive_q0"] is True


def test_one_unavailable_demod_channel_preserves_the_other_channel(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "29_channel_unavailable.py"))
    summary = cast("dict[str, object]", namespace["channel_unavailable_summary"])

    assert summary == {
        "records": 2,
        "q0_unavailable": 0,
        "q1_unavailable": 1,
        "q1_available_records": 1,
    }


def test_adaptive_tuneup_rediscovers_and_resumes(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "31_adaptive_tuneup.py"))
    summary = cast("dict[str, object]", namespace["adaptive_summary"])

    assert summary["initial_stages"] == 2
    assert summary["stopped_by_limit"] is True
    assert summary["rediscovered_stages"] == 2
    assert summary["completed_stages"] == 3
    assert summary["resumed_to_completion"] is True


def test_quantum_program_is_inspectable_without_hardware() -> None:
    namespace = run_path(str(NOTEBOOKS / "32_quantum_program_inspection.py"))
    summary = cast("dict[str, object]", namespace["program_inspection_summary"])

    assert summary == {
        "program_id": "drag-beta-rough-calibration",
        "description_has_ports": True,
        "tree_has_repeat": True,
        "tree_has_parallel_readout": True,
    }


def test_drag_calibration_closes_the_reviewed_config_loop(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "30_drag_calibration.py"))
    summary = cast("dict[str, object]", namespace["drag_beta_summary"])

    assert summary["status"] == "completed"
    assert summary["point_count"] == 15
    assert summary["candidate_run_uses_analysis"]
    assert summary["accepted_as_default"]
    assert summary["default_restored"]


def test_measurement_workbench_uses_real_durable_data(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "40_measurement_workbench.py"))
    summary = cast("dict[str, object]", namespace["measurement_summary"])

    assert summary["points"] == 3
    assert summary["nearest_points"] == 1
    assert summary["first_two_points"] == 2
    assert summary["available_points"] == 3
    assert summary["groups"] == 3
    assert summary["arrow_rows"] == 3
    assert summary["batch_sizes"] == [2, 1]
    assert summary["batch_offsets"] == [0, 2]


def test_ragged_and_partial_data_survive_daemon_boundaries(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "50_ragged_and_partial_data.py"))
    summary = cast("dict[str, object]", namespace["ragged_summary"])

    assert summary["ragged_shapes"] == [[2], [4], None, [1]]
    assert summary["window_shapes"] == [[2], [2], [1]]
    assert summary["partial_status"] == "failed"
    assert summary["partial_records"] == 1
    assert summary["expected_records"] == 3
