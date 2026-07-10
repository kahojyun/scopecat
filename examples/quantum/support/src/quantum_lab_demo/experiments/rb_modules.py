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
    .input(
        "clifford_count",
        value_type=sc.ScalarType(sc.IntType(minimum=1)),
    )
    .input("seed", value_type=sc.ScalarType(sc.IntType(minimum=0)))
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("qubit",),
    )
    .compute(
        "build-sqg-rb-sequence",
        fn=build_sqg_rb_sequence,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "qubit": sc.input("qubit"),
            "clifford_count": sc.var("clifford_count"),
            "seed": sc.input("seed"),
        },
    )
    .compute(
        "render-sqg-rb-pulse-program",
        fn=render_sqg_rb_pulse_program,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "sequence": sc.compute_result("build-sqg-rb-sequence"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        sc.compute_result("build-sqg-rb-sequence"),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-sqg-rb-pulse-program"),
    )
    .bind(
        "drive.play_gate_sequence.clifford_count",
        sc.var("clifford_count") * sc.Quantity(value=1.0, unit="count"),
    )
    .bind("drive.play_gate_sequence.seed", sc.input("seed"))
    .build()
)

CZ_RB_MODULE = (
    sc.module(CZ_RB_TEMPLATE_ID, metadata={"template_id": CZ_RB_TEMPLATE_ID})
    .entity_inputs_from("control_qubit", "partner_qubit", "coupler")
    .input(
        "clifford_count",
        value_type=sc.ScalarType(sc.IntType(minimum=1)),
    )
    .input("seed", value_type=sc.ScalarType(sc.IntType(minimum=0)))
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
    .input(
        "interleaved_gate",
        value_type=sc.ScalarType(sc.StringType(min_length=1)),
    )
    .compute(
        "build-cz-rb-sequence",
        fn=build_cz_rb_sequence,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
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
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "sequence": sc.compute_result("build-cz-rb-sequence"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        sc.compute_result("build-cz-rb-sequence"),
    )
    .bind(
        "drive.play_gate_sequence.clifford_count",
        sc.var("clifford_count") * sc.Quantity(value=1.0, unit="count"),
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        sc.compute_result("render-cz-rb-coupler-pulse"),
    )
    .bind("drive.play_gate_sequence.seed", sc.input("seed"))
    .build()
)

__all__ = [
    "CZ_RB_MODULE",
    "SQG_RB_MODULE",
]
