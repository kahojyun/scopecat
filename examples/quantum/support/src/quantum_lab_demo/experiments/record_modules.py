"""record declaration modules."""

from __future__ import annotations

import scopecat as sc

RAW_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.raw_iq")
    .product("raw_iq", resource="readout", unit="ratio", dtype="complex128")
    .build()
)

PROBABILITY_1_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.probability_1")
    .product("probability_1", resource="readout", unit=None)
    .build()
)

PROBABILITY_RECORDS_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.probability_01")
    .product("probability_0", "probability_1", resource="readout", unit=None)
    .build()
)

READOUT_CLASSIFICATION_RECORDS_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.readout_classification")
    .product("state0_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state1_iq", resource="readout", unit="ratio", dtype="complex128")
    .product("state0_iq_stdev", resource="readout", unit=None)
    .product("state1_iq_stdev", resource="readout", unit=None)
    .build()
)

MULTIPLEXED_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.multiplexed_iq")
    .input("qubits", kind="entity_array")
    .product(
        "multiplexed_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(sc.entity_axis("qubit", sc.input("qubits")),),
    )
    .build()
)

QND_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.qnd_iq")
    .input("rounds", kind="count")
    .input("shots", kind="count")
    .product(
        "qnd_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.record_axis("round", size=sc.input("rounds"), kind="repeat"),
            sc.shot_axis(sc.input("shots")),
        ),
    )
    .build()
)

STABILIZER_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.stabilizer_iq")
    .input("patch_qubits", kind="entity_array")
    .input("rounds", kind="count")
    .product(
        "stabilizer_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.record_axis("round", size=sc.input("rounds"), kind="repeat"),
            sc.entity_axis("qubit", sc.input("patch_qubits")),
        ),
    )
    .build()
)

BACKEND_PROBABILITY_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.backend_probabilities")
    .input("logical_points", kind="count")
    .product(
        "backend_probabilities",
        resource="readout",
        unit="ratio",
        axes=(
            sc.record_axis(
                "backend_point",
                size=sc.input("logical_points"),
                kind="backend_point",
                unit="count",
            ),
        ),
    )
    .build()
)

__all__ = [
    "BACKEND_PROBABILITY_RECORD_MODULE",
    "MULTIPLEXED_IQ_RECORD_MODULE",
    "PROBABILITY_1_RECORD_MODULE",
    "PROBABILITY_RECORDS_MODULE",
    "QND_IQ_RECORD_MODULE",
    "RAW_IQ_RECORD_MODULE",
    "READOUT_CLASSIFICATION_RECORDS_MODULE",
    "STABILIZER_IQ_RECORD_MODULE",
]
