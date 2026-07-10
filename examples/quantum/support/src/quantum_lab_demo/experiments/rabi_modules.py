"""Rabi experiment modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_rabi_gate_sequence,
    build_simultaneous_rabi_gate_sequence,
    render_rabi_waveforms,
    render_simultaneous_rabi_waveforms,
)
from quantum_lab_demo.experiments.ids import (
    RABI_TEMPLATE_ID,
    SIMULTANEOUS_RABI_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.parameter_refs import qubit_param

RABI_MODULE = (
    sc.module(RABI_TEMPLATE_ID, metadata={"template_id": RABI_TEMPLATE_ID})
    .entity("qubit")
    .input("drive_length", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "drive",
        requires=("play_pulse_program",),
        for_entities=("qubit",),
    )
    .compute(
        "build-rabi-gate-sequence",
        fn=build_rabi_gate_sequence,
        inputs={
            "qubit": sc.input("qubit"),
            "length": sc.var("drive_length"),
            "amplitude": qubit_param("rabi_drive_amplitude"),
            "frequency": qubit_param("drive_frequency"),
        },
    )
    .compute(
        "render-rabi-waveforms",
        fn=render_rabi_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-rabi-gate-sequence"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-rabi-waveforms"),
    )
    .bind("drive.play_pulse_program.length", sc.var("drive_length"))
    .bind("drive.play_pulse_program.amplitude", qubit_param("rabi_drive_amplitude"))
    .bind("drive.play_pulse_program.frequency", qubit_param("drive_frequency"))
    .build()
)

SIMULTANEOUS_RABI_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.rabi.simultaneous",
        metadata={"template_id": SIMULTANEOUS_RABI_TEMPLATE_ID},
    )
    .input(
        "qubits",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input("drive_length", value_type=sc.ScalarType(sc.QuantityType()))
    .input("drive_amplitude", value_type=sc.ScalarType(sc.QuantityType()))
    .input("drive_frequency", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "drive",
        requires=("play_pulse_program",),
        for_entities=("qubits",),
    )
    .compute(
        "build-simultaneous-rabi-gate-sequence",
        fn=build_simultaneous_rabi_gate_sequence,
        inputs={
            "qubits": sc.input_series("qubits"),
            "length": sc.var("drive_length"),
            "amplitude": sc.input("drive_amplitude"),
            "frequency": sc.input("drive_frequency"),
        },
    )
    .compute(
        "render-simultaneous-rabi-waveforms",
        fn=render_simultaneous_rabi_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-simultaneous-rabi-gate-sequence"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-simultaneous-rabi-waveforms"),
    )
    .bind("drive.play_pulse_program.length", sc.var("drive_length"))
    .bind("drive.play_pulse_program.amplitude", sc.input("drive_amplitude"))
    .bind("drive.play_pulse_program.frequency", sc.input("drive_frequency"))
    .build()
)

__all__ = [
    "RABI_MODULE",
    "SIMULTANEOUS_RABI_MODULE",
]
