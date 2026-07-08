"""randomized benchmarking modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_cz_rb_sequence,
    build_sqg_rb_sequence,
    render_cz_rb_coupler_pulse,
    render_sqg_rb_pulse_program,
)
from quantum_lab_demo.experiments.ids import CZ_RB_TEMPLATE_ID, SQG_RB_TEMPLATE_ID

SQG_RB_MODULE = (
    sc.module(SQG_RB_TEMPLATE_ID, metadata={"template_id": SQG_RB_TEMPLATE_ID})
    .entity("qubit")
    .input("clifford_count", kind="count")
    .input("seed", kind="seed")
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("qubit",),
    )
    .compute(
        "build-sqg-rb-sequence",
        fn=build_sqg_rb_sequence,
        inputs={
            "qubit": sc.input("qubit"),
            "clifford_count": sc.var("clifford_count"),
            "seed": sc.input("seed"),
        },
    )
    .compute(
        "render-sqg-rb-pulse-program",
        fn=render_sqg_rb_pulse_program,
        inputs={
            "sequence": sc.compute_result("build-sqg-rb-sequence"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .bind_compute(
        "drive.play_gate_sequence.sequence",
        "build-sqg-rb-sequence",
        kind="gate_sequence",
    )
    .bind_compute(
        "drive.play_pulse_program.program",
        "render-sqg-rb-pulse-program",
        kind="pulse_program",
    )
    .bind("drive.play_gate_sequence.clifford_count", sc.var("clifford_count"))
    .bind("drive.play_gate_sequence.seed", sc.input("seed"))
    .as_module()
)

CZ_RB_MODULE = (
    sc.module(CZ_RB_TEMPLATE_ID, metadata={"template_id": CZ_RB_TEMPLATE_ID})
    .entity_inputs_from("control_qubit", "partner_qubit", "coupler")
    .input("clifford_count", kind="count")
    .input("seed", kind="seed")
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("control_qubit", "partner_qubit"),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("coupler",),
    )
    .input("interleaved_gate", kind="gate_label")
    .compute(
        "build-cz-rb-sequence",
        fn=build_cz_rb_sequence,
        inputs={
            "control_qubit": sc.input("control_qubit"),
            "partner_qubit": sc.input("partner_qubit"),
            "coupler": sc.input("coupler"),
            "clifford_count": sc.var("clifford_count"),
            "seed": sc.input("seed"),
            "interleaved_gate": sc.input("interleaved_gate"),
        },
    )
    .compute(
        "render-cz-rb-coupler-pulse",
        fn=render_cz_rb_coupler_pulse,
        inputs={
            "sequence": sc.compute_result("build-cz-rb-sequence"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind_compute(
        "drive.play_gate_sequence.sequence",
        "build-cz-rb-sequence",
        kind="gate_sequence",
    )
    .bind("drive.play_gate_sequence.clifford_count", sc.var("clifford_count"))
    .bind_compute(
        "coupler.play_coupler_pulse.program",
        "render-cz-rb-coupler-pulse",
        kind="pulse_program",
    )
    .bind("drive.play_gate_sequence.seed", sc.input("seed"))
    .as_module()
)

__all__ = [
    "CZ_RB_MODULE",
    "SQG_RB_MODULE",
]
