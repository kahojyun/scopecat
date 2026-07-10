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
from quantum_lab_demo.experiments.points import DRIVE_LENGTH

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_QUANTITY = sc.ScalarType(sc.QuantityType())

_RABI_QUBIT = sc.input("qubit", _QUBIT)
_BUILD_RABI_SEQUENCE = sc.compute(
    "build-rabi-gate-sequence",
    fn=build_rabi_gate_sequence,
    inputs={
        "qubit": _RABI_QUBIT,
        "length": DRIVE_LENGTH,
        "amplitude": qubit_param("rabi_drive_amplitude", _RABI_QUBIT),
        "frequency": qubit_param("drive_frequency", _RABI_QUBIT),
    },
    output_type=sc.ScalarType(sc.PayloadType("quantum_lab_demo.rabi.gate_sequence")),
)
_RENDER_RABI_WAVEFORMS = sc.compute(
    "render-rabi-waveforms",
    fn=render_rabi_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_RABI_SEQUENCE.output,
        "drive_route": sc.route("drive"),
    },
)

RABI_MODULE = (
    sc.module(RABI_TEMPLATE_ID, metadata={"template_id": RABI_TEMPLATE_ID})
    .inputs(_RABI_QUBIT)
    .resource(
        "drive",
        requires=("play_pulse_program",),
        for_entities=(_RABI_QUBIT,),
    )
    .computes(_BUILD_RABI_SEQUENCE, _RENDER_RABI_WAVEFORMS)
    .bind(
        "drive.play_pulse_program.program",
        _RENDER_RABI_WAVEFORMS.output,
    )
    .bind("drive.play_pulse_program.length", DRIVE_LENGTH)
    .bind(
        "drive.play_pulse_program.amplitude",
        qubit_param("rabi_drive_amplitude", _RABI_QUBIT),
    )
    .bind(
        "drive.play_pulse_program.frequency",
        qubit_param("drive_frequency", _RABI_QUBIT),
    )
    .build()
)

_SIMULTANEOUS_QUBITS = sc.input("qubits", _QUBIT_SERIES)
_SIMULTANEOUS_DRIVE_AMPLITUDE = sc.input("drive_amplitude", _QUANTITY)
_SIMULTANEOUS_DRIVE_FREQUENCY = sc.input("drive_frequency", _QUANTITY)
_BUILD_SIMULTANEOUS_RABI_SEQUENCE = sc.compute(
    "build-simultaneous-rabi-gate-sequence",
    fn=build_simultaneous_rabi_gate_sequence,
    inputs={
        "qubits": _SIMULTANEOUS_QUBITS,
        "length": DRIVE_LENGTH,
        "amplitude": _SIMULTANEOUS_DRIVE_AMPLITUDE,
        "frequency": _SIMULTANEOUS_DRIVE_FREQUENCY,
    },
    output_type=sc.ScalarType(
        sc.PayloadType("quantum_lab_demo.simultaneous_rabi.gate_sequence")
    ),
)
_RENDER_SIMULTANEOUS_RABI_WAVEFORMS = sc.compute(
    "render-simultaneous-rabi-waveforms",
    fn=render_simultaneous_rabi_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_SIMULTANEOUS_RABI_SEQUENCE.output,
        "drive_route": sc.route("drive"),
    },
)

SIMULTANEOUS_RABI_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.rabi.simultaneous",
        metadata={"template_id": SIMULTANEOUS_RABI_TEMPLATE_ID},
    )
    .inputs(
        _SIMULTANEOUS_QUBITS,
        _SIMULTANEOUS_DRIVE_AMPLITUDE,
        _SIMULTANEOUS_DRIVE_FREQUENCY,
    )
    .resource(
        "drive",
        requires=("play_pulse_program",),
        for_entities=(_SIMULTANEOUS_QUBITS,),
    )
    .computes(
        _BUILD_SIMULTANEOUS_RABI_SEQUENCE,
        _RENDER_SIMULTANEOUS_RABI_WAVEFORMS,
    )
    .bind(
        "drive.play_pulse_program.program",
        _RENDER_SIMULTANEOUS_RABI_WAVEFORMS.output,
    )
    .bind("drive.play_pulse_program.length", DRIVE_LENGTH)
    .bind("drive.play_pulse_program.amplitude", _SIMULTANEOUS_DRIVE_AMPLITUDE)
    .bind("drive.play_pulse_program.frequency", _SIMULTANEOUS_DRIVE_FREQUENCY)
    .build()
)

__all__ = [
    "RABI_MODULE",
    "SIMULTANEOUS_RABI_MODULE",
]
