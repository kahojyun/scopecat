"""surface-code style modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_surface_code_round_program,
    render_surface_code_coupler_waveforms,
    render_surface_code_drive_waveforms,
)
from quantum_lab_demo.experiments.ids import TOY_SURFACE_CODE_ROUND_TEMPLATE_ID

TOY_SURFACE_CODE_ROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.surface_code.toy_round",
        metadata={"template_id": TOY_SURFACE_CODE_ROUND_TEMPLATE_ID},
    )
    .input(
        "patch_qubits",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input(
        "data_qubits",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input(
        "ancilla_qubits",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input(
        "couplers",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input(
        "rounds",
        value_type=sc.ScalarType(sc.IntType(minimum=1)),
    )
    .input("cycle_time", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("patch_qubits",),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("couplers",),
    )
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=("patch_qubits",),
    )
    .compute(
        "build-surface-code-round-program",
        fn=build_surface_code_round_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "patch_qubits": sc.input_series("patch_qubits"),
            "data_qubits": sc.input_series("data_qubits"),
            "ancilla_qubits": sc.input_series("ancilla_qubits"),
            "couplers": sc.input_series("couplers"),
            "rounds": sc.input("rounds"),
            "cycle_time": sc.input("cycle_time"),
        },
    )
    .compute(
        "render-surface-code-drive-waveforms",
        fn=render_surface_code_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-surface-code-round-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-surface-code-coupler-waveforms",
        fn=render_surface_code_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-surface-code-round-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        sc.compute_result("build-surface-code-round-program"),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-surface-code-drive-waveforms"),
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        sc.compute_result("render-surface-code-coupler-waveforms"),
    )
    .bind(
        "readout.acquire_iq.repetitions",
        sc.input("rounds") * sc.Quantity(value=1.0, unit="count"),
    )
    .build()
)

__all__ = [
    "TOY_SURFACE_CODE_ROUND_MODULE",
]
