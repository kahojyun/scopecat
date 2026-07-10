"""readout modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_multiplexed_readout_program,
    build_readout_program,
    build_repeated_measurement_program,
)
from quantum_lab_demo.experiments.ids import (
    MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
    MULTIPLEXED_READOUT_TEMPLATE_ID,
    QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.parameter_refs import qubit_param
from quantum_lab_demo.experiments.points import READOUT_FREQUENCY

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_QUANTITY = sc.ScalarType(sc.QuantityType())
_POSITIVE_INT = sc.ScalarType(sc.IntType(minimum=1))

READOUT_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.experiments.readout.capture")
    .resource(
        "readout",
        requires=("acquire_iq",),
    )
    .bind(
        "readout.acquire_iq.repetitions",
        sc.parameter("repetitions", _QUANTITY),
    )
    .build()
)

_READOUT_QUBIT = sc.input("qubit", _QUBIT)
_BUILD_READOUT_PROGRAM = sc.compute(
    "build-readout-frequency-program",
    fn=build_readout_program,
    output_type=sc.ScalarType(sc.PayloadType("readout_program")),
    inputs={
        "qubit": _READOUT_QUBIT,
        "frequency": READOUT_FREQUENCY,
        "power": qubit_param("readout_power", _READOUT_QUBIT),
    },
)

READOUT_MODULE = (
    sc.module(READOUT_TEMPLATE_ID, metadata={"template_id": READOUT_TEMPLATE_ID})
    .inputs(_READOUT_QUBIT)
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=(_READOUT_QUBIT,),
    )
    .computes(_BUILD_READOUT_PROGRAM)
    .bind(
        "readout.readout_pulse.program",
        _BUILD_READOUT_PROGRAM.output,
    )
    .bind("readout.readout_pulse.frequency", READOUT_FREQUENCY)
    .bind(
        "readout.readout_pulse.power",
        qubit_param("readout_power", _READOUT_QUBIT),
    )
    .build()
)

_MULTIPLEXED_QUBITS = sc.input("qubits", _QUBIT_SERIES)
_MULTIPLEXED_POWER = sc.input("readout_power", _QUANTITY)
_BUILD_MULTIPLEXED_READOUT_PROGRAM = sc.compute(
    "build-multiplexed-readout-program",
    fn=build_multiplexed_readout_program,
    output_type=sc.ScalarType(sc.PayloadType("readout_program")),
    inputs={
        "qubits": _MULTIPLEXED_QUBITS,
        "frequency": READOUT_FREQUENCY,
        "power": _MULTIPLEXED_POWER,
    },
)

MULTIPLEXED_READOUT_PULSE_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.multiplexed_pulse",
        metadata={"template_id": MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID},
    )
    .inputs(_MULTIPLEXED_QUBITS, _MULTIPLEXED_POWER)
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=(_MULTIPLEXED_QUBITS,),
    )
    .computes(_BUILD_MULTIPLEXED_READOUT_PROGRAM)
    .bind(
        "readout.readout_pulse.program",
        _BUILD_MULTIPLEXED_READOUT_PROGRAM.output,
    )
    .bind("readout.readout_pulse.frequency", READOUT_FREQUENCY)
    .bind("readout.readout_pulse.power", _MULTIPLEXED_POWER)
    .build()
)

_QND_QUBIT = sc.input("qubit", _QUBIT)
_QND_ROUNDS = sc.input("rounds", _POSITIVE_INT)
_QND_SHOTS = sc.input("shots", _POSITIVE_INT)
_BUILD_REPEATED_MEASUREMENT_PROGRAM = sc.compute(
    "build-repeated-measurement-program",
    fn=build_repeated_measurement_program,
    output_type=sc.ScalarType(sc.PayloadType("readout_program")),
    inputs={
        "qubit": _QND_QUBIT,
        "rounds": _QND_ROUNDS,
        "shots": _QND_SHOTS,
        "readout_frequency": qubit_param("readout_frequency", _QND_QUBIT),
    },
)

QND_REPEATED_MEASUREMENT_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.qnd_repeated_measurement",
        metadata={"template_id": QND_REPEATED_MEASUREMENT_TEMPLATE_ID},
    )
    .inputs(_QND_QUBIT, _QND_ROUNDS, _QND_SHOTS)
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=(_QND_QUBIT,),
    )
    .computes(_BUILD_REPEATED_MEASUREMENT_PROGRAM)
    .bind(
        "readout.readout_pulse.program",
        _BUILD_REPEATED_MEASUREMENT_PROGRAM.output,
    )
    .bind(
        "readout.readout_pulse.frequency",
        qubit_param("readout_frequency", _QND_QUBIT),
    )
    .bind(
        "readout.readout_pulse.power",
        qubit_param("readout_power", _QND_QUBIT),
    )
    .bind(
        "readout.acquire_iq.repetitions",
        _QND_SHOTS * sc.Quantity(value=1.0, unit="count"),
    )
    .build()
)

_MULTIPLEXED_CAPTURE_QUBITS = sc.input("qubits", _QUBIT_SERIES)

MULTIPLEXED_READOUT_MODULE = (
    sc.module(
        MULTIPLEXED_READOUT_TEMPLATE_ID,
        metadata={"template_id": MULTIPLEXED_READOUT_TEMPLATE_ID},
    )
    .inputs(_MULTIPLEXED_CAPTURE_QUBITS)
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=(_MULTIPLEXED_CAPTURE_QUBITS,),
    )
    .bind(
        "readout.acquire_iq.repetitions",
        sc.parameter("repetitions", _QUANTITY),
    )
    .build()
)

__all__ = [
    "MULTIPLEXED_READOUT_MODULE",
    "MULTIPLEXED_READOUT_PULSE_MODULE",
    "QND_REPEATED_MEASUREMENT_MODULE",
    "READOUT_CAPTURE_MODULE",
    "READOUT_MODULE",
]
