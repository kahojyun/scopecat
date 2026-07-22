"""randomized benchmarking modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_cz_rb_sequence,
    render_cz_rb_coupler_pulse,
)
from quantum_lab_demo.experiments.ids import CZ_RB_TEMPLATE_ID
from quantum_lab_demo.experiments.points import CLIFFORD_COUNT

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_NON_NEGATIVE_INT = sc.ScalarType(sc.IntType(minimum=0))
_NON_EMPTY_STRING = sc.ScalarType(sc.StringType(min_length=1))


@sc.module(id=CZ_RB_TEMPLATE_ID)
def CZ_RB_MODULE(
    control_qubit: Annotated[sc.Input[str], _QUBIT],
    partner_qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER],
    seed: Annotated[sc.Input[int], _NON_NEGATIVE_INT],
    interleaved_gate: Annotated[sc.Input[str], _NON_EMPTY_STRING],
):
    control_qubit_ref = cast("sc.ValueRef", control_qubit)
    partner_qubit_ref = cast("sc.ValueRef", partner_qubit)
    coupler_ref = cast("sc.ValueRef", coupler)
    seed_ref = cast("sc.ValueRef", seed)
    interleaved_gate_ref = cast("sc.ValueRef", interleaved_gate)
    build_sequence = sc.compute(
        "build-cz-rb-sequence",
        fn=build_cz_rb_sequence,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "control_qubit": control_qubit_ref,
            "partner_qubit": partner_qubit_ref,
            "coupler": coupler_ref,
            "clifford_count": CLIFFORD_COUNT,
            "seed": seed_ref,
            "interleaved_gate": interleaved_gate_ref,
        },
    )
    render_coupler_pulse = sc.compute(
        "render-cz-rb-coupler-pulse",
        fn=render_cz_rb_coupler_pulse,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"sequence": build_sequence.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence", "play_pulse_program"),
            for_entities=(control_qubit_ref, partner_qubit_ref),
        )
        .resource(
            "coupler",
            requires=("play_coupler_pulse",),
            for_entities=(coupler_ref,),
        )
        .computes(build_sequence, render_coupler_pulse)
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=build_sequence.output,
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
            value=render_coupler_pulse.output,
        )
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="seed",
            value=seed_ref,
        )
    )


__all__ = [
    "CZ_RB_MODULE",
]
