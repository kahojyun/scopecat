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

READOUT_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.experiments.readout.capture")
    .resource(
        "readout",
        requires=("acquire_iq",),
    )
    .bind("readout.acquire_iq.repetitions", sc.table_param("repetitions"))
    .build()
)

READOUT_MODULE = (
    sc.module(READOUT_TEMPLATE_ID, metadata={"template_id": READOUT_TEMPLATE_ID})
    .entity("qubit")
    .input("readout_frequency", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=("qubit",),
    )
    .compute(
        "build-readout-frequency-program",
        fn=build_readout_program,
        output_type=sc.ScalarType(sc.PayloadType("readout_program")),
        inputs={
            "qubit": sc.input("qubit"),
            "frequency": sc.var("readout_frequency"),
            "power": qubit_param("readout_power"),
        },
    )
    .bind(
        "readout.readout_pulse.program",
        sc.compute_result("build-readout-frequency-program"),
    )
    .bind("readout.readout_pulse.frequency", sc.var("readout_frequency"))
    .bind("readout.readout_pulse.power", qubit_param("readout_power"))
    .build()
)

MULTIPLEXED_READOUT_PULSE_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.multiplexed_pulse",
        metadata={"template_id": MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID},
    )
    .input("qubits", value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())))
    .input("readout_frequency", value_type=sc.ScalarType(sc.QuantityType()))
    .input("readout_power", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=("qubits",),
    )
    .compute(
        "build-multiplexed-readout-program",
        fn=build_multiplexed_readout_program,
        output_type=sc.ScalarType(sc.PayloadType("readout_program")),
        inputs={
            "qubits": sc.input_series("qubits"),
            "frequency": sc.var("readout_frequency"),
            "power": sc.input("readout_power"),
        },
    )
    .bind(
        "readout.readout_pulse.program",
        sc.compute_result("build-multiplexed-readout-program"),
    )
    .bind("readout.readout_pulse.frequency", sc.var("readout_frequency"))
    .bind("readout.readout_pulse.power", sc.input("readout_power"))
    .build()
)

QND_REPEATED_MEASUREMENT_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.qnd_repeated_measurement",
        metadata={"template_id": QND_REPEATED_MEASUREMENT_TEMPLATE_ID},
    )
    .entity("qubit")
    .input(
        "rounds",
        value_type=sc.ScalarType(sc.IntType(minimum=1)),
    )
    .input(
        "shots",
        value_type=sc.ScalarType(sc.IntType(minimum=1)),
    )
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=("qubit",),
    )
    .compute(
        "build-repeated-measurement-program",
        fn=build_repeated_measurement_program,
        output_type=sc.ScalarType(sc.PayloadType("readout_program")),
        inputs={
            "qubit": sc.input("qubit"),
            "rounds": sc.input("rounds"),
            "shots": sc.input("shots"),
            "readout_frequency": qubit_param("readout_frequency"),
        },
    )
    .bind(
        "readout.readout_pulse.program",
        sc.compute_result("build-repeated-measurement-program"),
    )
    .bind("readout.readout_pulse.frequency", qubit_param("readout_frequency"))
    .bind("readout.readout_pulse.power", qubit_param("readout_power"))
    .bind(
        "readout.acquire_iq.repetitions",
        sc.input("shots") * sc.Quantity(value=1.0, unit="count"),
    )
    .build()
)

MULTIPLEXED_READOUT_MODULE = (
    sc.module(
        MULTIPLEXED_READOUT_TEMPLATE_ID,
        metadata={"template_id": MULTIPLEXED_READOUT_TEMPLATE_ID},
    )
    .input("qubits", value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())))
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=("qubits",),
    )
    .bind("readout.acquire_iq.repetitions", sc.table_param("repetitions"))
    .build()
)

__all__ = [
    "MULTIPLEXED_READOUT_MODULE",
    "MULTIPLEXED_READOUT_PULSE_MODULE",
    "QND_REPEATED_MEASUREMENT_MODULE",
    "READOUT_CAPTURE_MODULE",
    "READOUT_MODULE",
]
