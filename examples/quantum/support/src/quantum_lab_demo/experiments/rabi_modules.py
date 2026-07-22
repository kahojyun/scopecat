"""Rabi experiment modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_rabi_gate_sequence,
    build_simultaneous_rabi_gate_sequence,
    render_rabi_waveforms,
    render_simultaneous_rabi_waveforms,
)
from quantum_lab_demo.experiments.ids import RABI_TEMPLATE_ID
from quantum_lab_demo.experiments.parameter_refs import qubit_param
from quantum_lab_demo.experiments.points import DRIVE_LENGTH

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_QUANTITY = sc.ScalarType(sc.QuantityType())


@sc.module(id=RABI_TEMPLATE_ID)
def RABI_MODULE(
    qubit: Annotated[sc.Input[str], _QUBIT],
):
    qubit_ref = cast("sc.ValueRef", qubit)
    build_sequence = sc.compute(
        "build-rabi-gate-sequence",
        fn=build_rabi_gate_sequence,
        inputs={
            "qubit": qubit_ref,
            "length": DRIVE_LENGTH,
            "amplitude": qubit_param("rabi_drive_amplitude", qubit_ref),
            "frequency": qubit_param("drive_frequency", qubit_ref),
        },
        output_type=sc.ScalarType(
            sc.PayloadType("quantum_lab_demo.rabi.gate_sequence")
        ),
    )
    render_waveforms = sc.compute(
        "render-rabi-waveforms",
        fn=render_rabi_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_sequence.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_pulse_program",),
            for_entities=(qubit_ref,),
        )
        .computes(build_sequence, render_waveforms)
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=render_waveforms.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="length",
            value=DRIVE_LENGTH,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="amplitude",
            value=qubit_param("rabi_drive_amplitude", qubit_ref),
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="frequency",
            value=qubit_param("drive_frequency", qubit_ref),
        )
    )


@sc.module(id="quantum_lab_demo.experiments.rabi.simultaneous")
def SIMULTANEOUS_RABI_MODULE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    drive_amplitude: Annotated[sc.Input[sc.Quantity], _QUANTITY],
    drive_frequency: Annotated[sc.Input[sc.Quantity], _QUANTITY],
):
    qubits_ref = cast("sc.ValueRef", qubits)
    drive_amplitude_ref = cast("sc.ValueRef", drive_amplitude)
    drive_frequency_ref = cast("sc.ValueRef", drive_frequency)
    build_sequence = sc.compute(
        "build-simultaneous-rabi-gate-sequence",
        fn=build_simultaneous_rabi_gate_sequence,
        inputs={
            "qubits": qubits_ref,
            "length": DRIVE_LENGTH,
            "amplitude": drive_amplitude_ref,
            "frequency": drive_frequency_ref,
        },
        output_type=sc.ScalarType(
            sc.PayloadType("quantum_lab_demo.simultaneous_rabi.gate_sequence")
        ),
    )
    render_waveforms = sc.compute(
        "render-simultaneous-rabi-waveforms",
        fn=render_simultaneous_rabi_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_sequence.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_pulse_program",),
            for_entities=(qubits_ref,),
        )
        .computes(build_sequence, render_waveforms)
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=render_waveforms.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="length",
            value=DRIVE_LENGTH,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="amplitude",
            value=drive_amplitude_ref,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="frequency",
            value=drive_frequency_ref,
        )
    )


__all__ = [
    "RABI_MODULE",
    "SIMULTANEOUS_RABI_MODULE",
]
