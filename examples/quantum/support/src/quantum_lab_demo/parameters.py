"""Typed parameter schema and initial values for the runnable quantum lab."""

from __future__ import annotations

import scopecat as sc
from scopecat.records.parameter import (
    ParameterSnapshot,
    TableParameterValue,
)

QUBIT = sc.parameter_field(
    "qubit",
    sc.EntityType(entity_kind="logical_qubit"),
)
DRAG_BETA = sc.parameter_field("drag_beta", sc.QuantityType(unit="ns"))
QUARTER_TURN_DURATION = sc.parameter_field(
    "quarter_turn_duration",
    sc.QuantityType(unit="ns"),
)
QUARTER_TURN_AMPLITUDE = sc.parameter_field(
    "quarter_turn_amplitude",
    sc.QuantityType(unit="arb"),
)
QUARTER_TURN_SIGMA = sc.parameter_field(
    "quarter_turn_sigma",
    sc.QuantityType(unit="ns"),
)
QUBITS = sc.parameter_schema(
    "qubits",
    fields=(
        QUBIT,
        DRAG_BETA,
        QUARTER_TURN_DURATION,
        QUARTER_TURN_AMPLITUDE,
        QUARTER_TURN_SIGMA,
    ),
    primary_key=(QUBIT,),
    description="q0 DRAG calibration values.",
)
Q0 = QUBITS.row(
    QUBIT.key("q0"),
)
Q0_DRAG_BETA = Q0[DRAG_BETA]

QUANTUM_PARAMETER_CATALOG = sc.parameter_catalog(
    "quantum-demo-parameter-definitions-catalog",
    QUBITS,
)


def quantum_lab_parameter_snapshot() -> ParameterSnapshot:
    """Build the initial scalar and calibration tables reviewed in source."""

    return ParameterSnapshot(
        id="quantum-demo-parameter-snapshot",
        values=(
            TableParameterValue(
                id=QUBITS.id,
                rows=(
                    Q0.values(
                        DRAG_BETA.value(0.5),
                        QUARTER_TURN_DURATION.value(16.0),
                        QUARTER_TURN_AMPLITUDE.value(0.2),
                        QUARTER_TURN_SIGMA.value(4.0),
                    ),
                ),
            ),
        ),
    )


__all__ = [
    "DRAG_BETA",
    "Q0",
    "Q0_DRAG_BETA",
    "QUANTUM_PARAMETER_CATALOG",
    "QUARTER_TURN_AMPLITUDE",
    "QUARTER_TURN_DURATION",
    "QUARTER_TURN_SIGMA",
    "QUBIT",
    "QUBITS",
    "quantum_lab_parameter_snapshot",
]
