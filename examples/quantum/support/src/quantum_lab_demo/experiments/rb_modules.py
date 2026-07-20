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
from quantum_lab_demo.experiments.points import CLIFFORD_COUNT

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_NON_NEGATIVE_INT = sc.ScalarType(sc.IntType(minimum=0))

_SQG_QUBIT = sc.input("qubit", _QUBIT)
_SQG_SEED = sc.input("seed", _NON_NEGATIVE_INT)
_BUILD_SQG_RB_SEQUENCE = sc.compute(
    "build-sqg-rb-sequence",
    fn=build_sqg_rb_sequence,
    output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
    inputs={
        "qubit": _SQG_QUBIT,
        "clifford_count": CLIFFORD_COUNT,
        "seed": _SQG_SEED,
    },
)
_RENDER_SQG_RB_PULSE_PROGRAM = sc.compute(
    "render-sqg-rb-pulse-program",
    fn=render_sqg_rb_pulse_program,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "sequence": _BUILD_SQG_RB_SEQUENCE.output,
    },
)

SQG_RB_MODULE = (
    sc.module(SQG_RB_TEMPLATE_ID)
    .inputs(_SQG_QUBIT, _SQG_SEED)
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(_SQG_QUBIT,),
    )
    .computes(_BUILD_SQG_RB_SEQUENCE, _RENDER_SQG_RB_PULSE_PROGRAM)
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="sequence",
        value=_BUILD_SQG_RB_SEQUENCE.output,
    )
    .bind_field(
        "drive",
        capability="play_pulse_program",
        field="program",
        value=_RENDER_SQG_RB_PULSE_PROGRAM.output,
    )
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="clifford_count",
        value=CLIFFORD_COUNT * sc.Quantity(value=1.0, unit="count"),
    )
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="seed",
        value=_SQG_SEED,
    )
    .build()
)

_CZ_CONTROL_QUBIT = sc.input("control_qubit", _QUBIT)
_CZ_PARTNER_QUBIT = sc.input("partner_qubit", _QUBIT)
_CZ_COUPLER = sc.input("coupler", _COUPLER)
_CZ_SEED = sc.input("seed", _NON_NEGATIVE_INT)
_CZ_INTERLEAVED_GATE = sc.input(
    "interleaved_gate",
    sc.ScalarType(sc.StringType(min_length=1)),
)
_BUILD_CZ_RB_SEQUENCE = sc.compute(
    "build-cz-rb-sequence",
    fn=build_cz_rb_sequence,
    output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
    inputs={
        "control_qubit": _CZ_CONTROL_QUBIT,
        "partner_qubit": _CZ_PARTNER_QUBIT,
        "coupler": _CZ_COUPLER,
        "clifford_count": CLIFFORD_COUNT,
        "seed": _CZ_SEED,
        "interleaved_gate": _CZ_INTERLEAVED_GATE,
    },
)
_RENDER_CZ_RB_COUPLER_PULSE = sc.compute(
    "render-cz-rb-coupler-pulse",
    fn=render_cz_rb_coupler_pulse,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "sequence": _BUILD_CZ_RB_SEQUENCE.output,
    },
)

CZ_RB_MODULE = (
    sc.module(CZ_RB_TEMPLATE_ID)
    .inputs(
        _CZ_CONTROL_QUBIT,
        _CZ_PARTNER_QUBIT,
        _CZ_COUPLER,
        _CZ_SEED,
        _CZ_INTERLEAVED_GATE,
    )
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(_CZ_CONTROL_QUBIT, _CZ_PARTNER_QUBIT),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=(_CZ_COUPLER,),
    )
    .computes(_BUILD_CZ_RB_SEQUENCE, _RENDER_CZ_RB_COUPLER_PULSE)
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="sequence",
        value=_BUILD_CZ_RB_SEQUENCE.output,
    )
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="clifford_count",
        value=CLIFFORD_COUNT * sc.Quantity(value=1.0, unit="count"),
    )
    .bind_field(
        "coupler",
        capability="play_coupler_pulse",
        field="program",
        value=_RENDER_CZ_RB_COUPLER_PULSE.output,
    )
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="seed",
        value=_CZ_SEED,
    )
    .build()
)

__all__ = [
    "CZ_RB_MODULE",
    "SQG_RB_MODULE",
]
