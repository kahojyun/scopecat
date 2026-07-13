"""surface-code style modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_surface_code_round_program,
    render_surface_code_coupler_waveforms,
    render_surface_code_drive_waveforms,
)
from quantum_lab_demo.experiments.ids import TOY_SURFACE_CODE_ROUND_TEMPLATE_ID

_QUBIT_SERIES = sc.SeriesType(sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")))
_COUPLER_SERIES = sc.SeriesType(
    sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
)
_PATCH_QUBITS = sc.input("patch_qubits", _QUBIT_SERIES)
_DATA_QUBITS = sc.input("data_qubits", _QUBIT_SERIES)
_ANCILLA_QUBITS = sc.input("ancilla_qubits", _QUBIT_SERIES)
_COUPLERS = sc.input("couplers", _COUPLER_SERIES)
_ROUNDS = sc.input("rounds", sc.ScalarType(sc.IntType(minimum=1)))
_CYCLE_TIME = sc.input("cycle_time", sc.ScalarType(sc.QuantityType()))
_BUILD_SURFACE_CODE_ROUND_PROGRAM = sc.compute(
    "build-surface-code-round-program",
    fn=build_surface_code_round_program,
    output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
    inputs={
        "patch_qubits": _PATCH_QUBITS,
        "data_qubits": _DATA_QUBITS,
        "ancilla_qubits": _ANCILLA_QUBITS,
        "couplers": _COUPLERS,
        "rounds": _ROUNDS,
        "cycle_time": _CYCLE_TIME,
    },
)
_RENDER_SURFACE_CODE_DRIVE_WAVEFORMS = sc.compute(
    "render-surface-code-drive-waveforms",
    fn=render_surface_code_drive_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_SURFACE_CODE_ROUND_PROGRAM.output,
        "drive_route": sc.route("drive"),
    },
)
_RENDER_SURFACE_CODE_COUPLER_WAVEFORMS = sc.compute(
    "render-surface-code-coupler-waveforms",
    fn=render_surface_code_coupler_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_SURFACE_CODE_ROUND_PROGRAM.output,
        "coupler_route": sc.route("coupler"),
    },
)

TOY_SURFACE_CODE_ROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.surface_code.toy_round",
        metadata={"template_id": TOY_SURFACE_CODE_ROUND_TEMPLATE_ID},
    )
    .inputs(
        _PATCH_QUBITS,
        _DATA_QUBITS,
        _ANCILLA_QUBITS,
        _COUPLERS,
        _ROUNDS,
        _CYCLE_TIME,
    )
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(_PATCH_QUBITS,),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=(_COUPLERS,),
    )
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=(_PATCH_QUBITS,),
    )
    .computes(
        _BUILD_SURFACE_CODE_ROUND_PROGRAM,
        _RENDER_SURFACE_CODE_DRIVE_WAVEFORMS,
        _RENDER_SURFACE_CODE_COUPLER_WAVEFORMS,
    )
    .bind_field(
        "drive",
        capability="play_gate_sequence",
        field="sequence",
        value=_BUILD_SURFACE_CODE_ROUND_PROGRAM.output,
    )
    .bind_field(
        "drive",
        capability="play_pulse_program",
        field="program",
        value=_RENDER_SURFACE_CODE_DRIVE_WAVEFORMS.output,
    )
    .bind_field(
        "coupler",
        capability="play_coupler_pulse",
        field="program",
        value=_RENDER_SURFACE_CODE_COUPLER_WAVEFORMS.output,
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=_ROUNDS * sc.Quantity(value=1.0, unit="count"),
    )
    .product(
        "stabilizer_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.record_axis("round", size=_ROUNDS, kind="repeat"),
            sc.entity_axis("qubit", _PATCH_QUBITS),
        ),
    )
    .build()
)

__all__ = [
    "TOY_SURFACE_CODE_ROUND_MODULE",
]
