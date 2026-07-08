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
    .as_module()
)

READOUT_MODULE = (
    sc.module(READOUT_TEMPLATE_ID, metadata={"template_id": READOUT_TEMPLATE_ID})
    .entity("qubit")
    .input("readout_frequency", kind="quantity")
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=("qubit",),
    )
    .compute(
        "build-readout-frequency-program",
        fn=build_readout_program,
        inputs={
            "qubit": sc.input("qubit"),
            "frequency": sc.var("readout_frequency"),
            "power": qubit_param("readout_power"),
        },
    )
    .bind_compute(
        "readout.readout_pulse.program",
        "build-readout-frequency-program",
        kind="readout_program",
    )
    .bind("readout.readout_pulse.frequency", sc.var("readout_frequency"))
    .bind("readout.readout_pulse.power", qubit_param("readout_power"))
    .as_module()
)

MULTIPLEXED_READOUT_PULSE_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.multiplexed_pulse",
        metadata={"template_id": MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID},
    )
    .input("qubits", kind="entity_array")
    .input("readout_frequency", kind="quantity")
    .input("readout_power", kind="quantity")
    .resource(
        "readout",
        requires=("readout_pulse",),
        for_entities=("qubits",),
    )
    .compute(
        "build-multiplexed-readout-program",
        fn=build_multiplexed_readout_program,
        inputs={
            "qubits": sc.input("qubits"),
            "frequency": sc.var("readout_frequency"),
            "power": sc.input("readout_power"),
        },
    )
    .bind_compute(
        "readout.readout_pulse.program",
        "build-multiplexed-readout-program",
        kind="readout_program",
    )
    .bind("readout.readout_pulse.frequency", sc.var("readout_frequency"))
    .bind("readout.readout_pulse.power", sc.input("readout_power"))
    .as_module()
)

QND_REPEATED_MEASUREMENT_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.readout.qnd_repeated_measurement",
        metadata={"template_id": QND_REPEATED_MEASUREMENT_TEMPLATE_ID},
    )
    .entity("qubit")
    .input("rounds", kind="count")
    .input("shots", kind="count")
    .resource(
        "readout",
        requires=("readout_pulse", "acquire_iq"),
        for_entities=("qubit",),
    )
    .compute(
        "build-repeated-measurement-program",
        fn=build_repeated_measurement_program,
        inputs={
            "qubit": sc.input("qubit"),
            "rounds": sc.input("rounds"),
            "shots": sc.input("shots"),
            "readout_frequency": qubit_param("readout_frequency"),
        },
    )
    .bind_compute(
        "readout.readout_pulse.program",
        "build-repeated-measurement-program",
        kind="readout_program",
    )
    .bind("readout.readout_pulse.frequency", qubit_param("readout_frequency"))
    .bind("readout.readout_pulse.power", qubit_param("readout_power"))
    .bind("readout.acquire_iq.repetitions", sc.input("shots"))
    .as_module()
)

MULTIPLEXED_READOUT_MODULE = (
    sc.module(
        MULTIPLEXED_READOUT_TEMPLATE_ID,
        metadata={"template_id": MULTIPLEXED_READOUT_TEMPLATE_ID},
    )
    .input("qubits", kind="entity_array")
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=("qubits",),
    )
    .bind("readout.acquire_iq.repetitions", sc.table_param("repetitions"))
    .as_module()
)

__all__ = [
    "MULTIPLEXED_READOUT_MODULE",
    "MULTIPLEXED_READOUT_PULSE_MODULE",
    "QND_REPEATED_MEASUREMENT_MODULE",
    "READOUT_CAPTURE_MODULE",
    "READOUT_MODULE",
]
