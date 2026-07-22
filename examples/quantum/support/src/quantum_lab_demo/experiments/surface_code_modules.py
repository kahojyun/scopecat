"""surface-code style modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_surface_code_round_program,
    render_surface_code_coupler_waveforms,
    render_surface_code_drive_waveforms,
)

_QUBIT_SERIES = sc.SeriesType(sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")))
_COUPLER_SERIES = sc.SeriesType(
    sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
)
_POSITIVE_INT = sc.ScalarType(sc.IntType(minimum=1))
_QUANTITY = sc.ScalarType(sc.QuantityType())


@sc.module(id="quantum_lab_demo.experiments.surface_code.toy_round")
def TOY_SURFACE_CODE_ROUND_MODULE(
    patch_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    data_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    ancilla_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES],
    rounds: Annotated[sc.Input[int], _POSITIVE_INT],
    cycle_time: Annotated[sc.Input[sc.Quantity], _QUANTITY],
):
    patch_qubits_ref = cast("sc.ValueRef", patch_qubits)
    data_qubits_ref = cast("sc.ValueRef", data_qubits)
    ancilla_qubits_ref = cast("sc.ValueRef", ancilla_qubits)
    couplers_ref = cast("sc.ValueRef", couplers)
    rounds_ref = cast("sc.ValueRef", rounds)
    cycle_time_ref = cast("sc.ValueRef", cycle_time)
    build_program = sc.compute(
        "build-surface-code-round-program",
        fn=build_surface_code_round_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "patch_qubits": patch_qubits_ref,
            "data_qubits": data_qubits_ref,
            "ancilla_qubits": ancilla_qubits_ref,
            "couplers": couplers_ref,
            "rounds": rounds_ref,
            "cycle_time": cycle_time_ref,
        },
    )
    render_drive_waveforms = sc.compute(
        "render-surface-code-drive-waveforms",
        fn=render_surface_code_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    render_coupler_waveforms = sc.compute(
        "render-surface-code-coupler-waveforms",
        fn=render_surface_code_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence", "play_pulse_program"),
            for_entities=(patch_qubits_ref,),
        )
        .resource(
            "coupler",
            requires=("play_coupler_pulse",),
            for_entities=(couplers_ref,),
        )
        .resource(
            "readout",
            requires=("acquire_iq",),
            for_entities=(patch_qubits_ref,),
        )
        .computes(build_program, render_drive_waveforms, render_coupler_waveforms)
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=build_program.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=render_drive_waveforms.output,
        )
        .bind_field(
            "coupler",
            capability="play_coupler_pulse",
            field="program",
            value=render_coupler_waveforms.output,
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=rounds_ref * sc.Quantity(value=1.0, unit="count"),
        )
        .product(
            "stabilizer_iq",
            unit="ratio",
            dtype="complex128",
            axes=(
                sc.product_axis("round", size=rounds_ref, kind="repeat"),
                sc.entity_axis("qubit", patch_qubits_ref),
            ),
        )
        .acquire(
            "read-stabilizer-iq",
            "stabilizer_iq",
            resource="readout",
            capability="acquire_iq",
        )
    )


__all__ = [
    "TOY_SURFACE_CODE_ROUND_MODULE",
]
