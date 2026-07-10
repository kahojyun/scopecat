"""record declaration modules."""

from __future__ import annotations

import scopecat as sc

_QUBIT_SERIES = sc.SeriesType(sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")))
_POSITIVE_INT = sc.ScalarType(sc.IntType(minimum=1))

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

_MULTIPLEXED_QUBITS = sc.input("qubits", _QUBIT_SERIES)
MULTIPLEXED_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.multiplexed_iq")
    .inputs(_MULTIPLEXED_QUBITS)
    .product(
        "multiplexed_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(sc.entity_axis("qubit", _MULTIPLEXED_QUBITS),),
    )
    .build()
)

_QND_ROUNDS = sc.input("rounds", _POSITIVE_INT)
_QND_SHOTS = sc.input("shots", _POSITIVE_INT)
QND_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.qnd_iq")
    .inputs(_QND_ROUNDS, _QND_SHOTS)
    .product(
        "qnd_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.record_axis("round", size=_QND_ROUNDS, kind="repeat"),
            sc.shot_axis(_QND_SHOTS),
        ),
    )
    .build()
)

_STABILIZER_PATCH_QUBITS = sc.input("patch_qubits", _QUBIT_SERIES)
_STABILIZER_ROUNDS = sc.input("rounds", _POSITIVE_INT)
STABILIZER_IQ_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.stabilizer_iq")
    .inputs(_STABILIZER_PATCH_QUBITS, _STABILIZER_ROUNDS)
    .product(
        "stabilizer_iq",
        resource="readout",
        unit="ratio",
        dtype="complex128",
        axes=(
            sc.record_axis("round", size=_STABILIZER_ROUNDS, kind="repeat"),
            sc.entity_axis("qubit", _STABILIZER_PATCH_QUBITS),
        ),
    )
    .build()
)

_BACKEND_LOGICAL_POINTS = sc.input("logical_points", _POSITIVE_INT)
BACKEND_PROBABILITY_RECORD_MODULE = (
    sc.module("quantum_lab_demo.experiments.records.backend_probabilities")
    .inputs(_BACKEND_LOGICAL_POINTS)
    .product(
        "backend_probabilities",
        resource="readout",
        unit="ratio",
        axes=(
            sc.record_axis(
                "backend_point",
                size=_BACKEND_LOGICAL_POINTS,
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
