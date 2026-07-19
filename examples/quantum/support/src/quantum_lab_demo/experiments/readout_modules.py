"""readout modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_multiplexed_readout_program,
    build_readout_program,
    build_repeated_measurement_program,
)
from quantum_lab_demo.experiments.ids import (
    MULTIPLEXED_READOUT_TEMPLATE_ID,
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
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=sc.parameter("repetitions", _QUANTITY),
    )
    .product("raw_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("probability_0", "probability_1", resource="readout", unit=None)
    .product("state0_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state1_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state0_iq_stdev", resource="readout", unit=None)
    .product("state1_iq_stdev", resource="readout", unit=None)
    .acquire(
        "read-capture",
        "raw_iq",
        "probability_0",
        "probability_1",
        "state0_iq",
        "state1_iq",
        "state0_iq_stdev",
        "state1_iq_stdev",
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
    sc.module(READOUT_TEMPLATE_ID)
    .inputs(_READOUT_QUBIT)
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=(_READOUT_QUBIT,),
    )
    .computes(_BUILD_READOUT_PROGRAM)
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="program",
        value=_BUILD_READOUT_PROGRAM.output,
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="frequency",
        value=READOUT_FREQUENCY,
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="power",
        value=qubit_param("readout_power", _READOUT_QUBIT),
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=sc.parameter("repetitions", _QUANTITY),
    )
    .product("raw_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state0_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state1_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state0_iq_stdev", resource="readout", unit=None)
    .product("state1_iq_stdev", resource="readout", unit=None)
    .acquire(
        "read-iq",
        "raw_iq",
        "state0_iq",
        "state1_iq",
        "state0_iq_stdev",
        "state1_iq_stdev",
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
    )
    .inputs(_MULTIPLEXED_QUBITS, _MULTIPLEXED_POWER)
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=(_MULTIPLEXED_QUBITS,),
    )
    .computes(_BUILD_MULTIPLEXED_READOUT_PROGRAM)
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="program",
        value=_BUILD_MULTIPLEXED_READOUT_PROGRAM.output,
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="frequency",
        value=READOUT_FREQUENCY,
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="power",
        value=_MULTIPLEXED_POWER,
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=sc.parameter("repetitions", _QUANTITY),
    )
    .product(
        "multiplexed_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(sc.entity_axis("qubit", _MULTIPLEXED_QUBITS),),
    )
    .acquire("read-multiplexed-iq", "multiplexed_iq")
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
    )
    .inputs(_QND_QUBIT, _QND_ROUNDS, _QND_SHOTS)
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=(_QND_QUBIT,),
    )
    .computes(_BUILD_REPEATED_MEASUREMENT_PROGRAM)
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="program",
        value=_BUILD_REPEATED_MEASUREMENT_PROGRAM.output,
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="frequency",
        value=qubit_param("readout_frequency", _QND_QUBIT),
    )
    .bind_field(
        "readout",
        capability="readout_pulse",
        field="power",
        value=qubit_param("readout_power", _QND_QUBIT),
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=_QND_SHOTS * sc.Quantity(value=1.0, unit="count"),
    )
    .product(
        "qnd_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.product_axis("round", size=_QND_ROUNDS, kind="repeat"),
            sc.shot_axis(_QND_SHOTS),
        ),
    )
    .acquire("read-qnd-iq", "qnd_iq")
    .build()
)

_MULTIPLEXED_CAPTURE_QUBITS = sc.input("qubits", _QUBIT_SERIES)

MULTIPLEXED_READOUT_MODULE = (
    sc.module(
        MULTIPLEXED_READOUT_TEMPLATE_ID,
    )
    .inputs(_MULTIPLEXED_CAPTURE_QUBITS)
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=(_MULTIPLEXED_CAPTURE_QUBITS,),
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=sc.parameter("repetitions", _QUANTITY),
    )
    .product(
        "multiplexed_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(sc.entity_axis("qubit", _MULTIPLEXED_CAPTURE_QUBITS),),
    )
    .acquire("read-multiplexed-iq", "multiplexed_iq")
    .build()
)

__all__ = [
    "MULTIPLEXED_READOUT_MODULE",
    "MULTIPLEXED_READOUT_PULSE_MODULE",
    "QND_REPEATED_MEASUREMENT_MODULE",
    "READOUT_CAPTURE_MODULE",
    "READOUT_MODULE",
]
