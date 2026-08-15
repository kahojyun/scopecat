from __future__ import annotations

from pathlib import Path
from runpy import run_path
from typing import Protocol, cast

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import MeasurementTracePreviewQuery


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
        "pump-source",
        "bench-source",
        "drive-lo-a",
        "drive-lo-b",
        "readout-lo",
        "drive-awg",
        "readout-awg",
        "readout-digitizer",
        "timing-controller",
        "bench-scope",
        "flux-dac-a",
        "flux-dac-b",
        "mixing-chamber",
        "readout-vna",
    }
    assert summary["parameter_rows"] == {
        "qubits": 4,
        "iq_chains": 5,
        "awg_output_baselines": 1,
        "lo_groups": 3,
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
            "q0": {"i": "drive.awg0.ch1", "q": "drive.awg0.ch2"},
            "q1": {"i": "drive.awg0.ch3", "q": "drive.awg0.ch4"},
            "q2": {"i": "drive.awg0.ch5", "q": "drive.awg0.ch6"},
            "q3": {"i": "drive.awg0.ch7", "q": "drive.awg0.ch8"},
        },
        "readout": {
            "q0": {"i": "readout.awg0.ch1", "q": "readout.awg0.ch2"},
            "q1": {"i": "readout.awg0.ch1", "q": "readout.awg0.ch2"},
            "q2": {"i": "readout.awg0.ch1", "q": "readout.awg0.ch2"},
            "q3": {"i": "readout.awg0.ch1", "q": "readout.awg0.ch2"},
        },
        "acquisition": {
            "q0": {
                "adc": ("readout-digitizer", ("inputs", "ch1")),
                "demodulator": "demod0",
            },
            "q1": {
                "adc": ("readout-digitizer", ("inputs", "ch1")),
                "demodulator": "demod1",
            },
            "q2": {
                "adc": ("readout-digitizer", ("inputs", "ch1")),
                "demodulator": "demod2",
            },
            "q3": {
                "adc": ("readout-digitizer", ("inputs", "ch1")),
                "demodulator": "demod3",
            },
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


def test_xy_lo_sweep_records_carriers_from_signed_if(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "34_xy_lo_sweep.py"))
    summary = cast("dict[str, object]", namespace["xy_lo_sweep_summary"])

    assert summary == {
        "requested_lo_ghz": [4.9, 4.91, 4.92],
        "requested_signed_if_mhz": {"q0": 100.0, "q1": -100.0},
        "requested_carrier_ghz": {
            "q0": [5.0, 5.01, 5.02],
            "q1": [4.8, 4.81, 4.82],
        },
        "status": "completed",
    }


def test_awg_output_monitor_records_entityless_bench_capture(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "35_awg_output_monitor.py"))
    summary = cast("dict[str, object]", namespace["awg_output_monitor_summary"])

    assert summary == {
        "name": "AWG CH1 pulse shape after bench recabling",
        "tags": ["diagnostic", "awg-monitor"],
        "description_mentions_wiring": True,
        "samples": 16,
        "time_end_ns": 15.0,
        "peak_mv": 250.0,
        "minimum_mv": -20.0,
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


def test_fixed_if_lo_sweep_keeps_lo_outside_the_quantum_target(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "36_q0_fixed_if_lo_sweep.py"))
    summary = cast("dict[str, object]", namespace["q0_fixed_if_lo_sweep_summary"])

    assert summary == {
        "points": 3,
        "signed_if_mhz": [-50.0],
        "carrier_ghz": [4.79, 4.8, 4.81],
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


def test_entity_axis_preserves_the_available_demod_channel(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "29_channel_unavailable.py"))
    summary = cast("dict[str, object]", namespace["channel_unavailable_summary"])

    assert isinstance(summary["run_id"], str)
    assert summary["status"] == "completed"
    assert summary["records"] == 2
    assert summary["variable"] == "iq_shots"
    assert summary["dims"] == [
        "point",
        "logical_qubit",
        "shared/parallel-two-qubit-ramsey/shot",
    ]
    assert summary["shape"] == [2, 2, 64]
    assert summary["entities"] == ["q0", "q1"]
    assert summary["available_points"] == {"q0": 2, "q1": 1}
    assert summary["unavailable_reasons"] == {"q0": [], "q1": ["missing"]}
    source_results = cast("dict[str, str]", summary["source_results"])
    assert source_results.keys() == {"q0", "q1"}
    assert source_results["q0"].endswith("q0_iq_shots")
    assert source_results["q1"].endswith("q1_iq_shots")
    assert summary["acquisition_policy"] == "independent"
    with DaemonClient(reference_lab_daemon.url) as client:
        trace = client.measurement_trace_preview(
            summary["run_id"],
            MeasurementTracePreviewQuery(
                observable_id="iq_shots",
                entity_indices=(0, 1),
                max_series=4,
                max_samples=256,
            ),
        )
    assert [series.label for series in trace.series] == [
        "Delay 88 ns · q0",
        "Delay 88 ns · q1",
        "Delay 128 ns · q0",
    ]
    assert [failure.label for failure in trace.failures] == ["Delay 128 ns · q1"]


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
    assert summary["output_kinds"] == [
        "dataset",
        "fact",
        "table",
        "figure",
        "artifact",
        "parameter_change_proposal",
    ]
    assert summary["execution_evidence"] == 0
    assert summary["fit_report"] == "drag-beta-fit.md"
    assert summary["proposal_evidence"] == ("quadratic-fit", "observations")
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


def test_ragged_scope_data_survives_daemon_boundaries(
    reference_lab_daemon: _ReferenceLabDaemon,
) -> None:
    assert reference_lab_daemon.url.startswith("http://127.0.0.1:")
    namespace = run_path(str(NOTEBOOKS / "50_ragged_scope_capture.py"))
    summary = cast("dict[str, object]", namespace["ragged_scope_summary"])

    assert summary == {
        "record_lengths": [4, 7, 10],
        "ragged_shapes": [[4], [7], [10]],
        "window_shapes": [[2], [2], [2]],
        "status": "completed",
    }
