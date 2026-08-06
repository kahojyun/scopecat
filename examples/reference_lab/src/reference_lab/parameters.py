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

RESONATOR = sc.parameter_field(
    "resonator",
    sc.EntityType(entity_kind="logical_qubit"),
)
RESONANCE_FREQUENCY = sc.parameter_field(
    "resonance_frequency",
    sc.QuantityType(unit="Hz"),
)
RESONATOR_LINEWIDTH = sc.parameter_field(
    "linewidth",
    sc.QuantityType(unit="Hz"),
)
FLUX_SWEET_SPOT = sc.parameter_field(
    "flux_sweet_spot",
    sc.QuantityType(unit="V"),
)
READOUT_RESONATORS = sc.parameter_schema(
    "readout_resonators",
    fields=(
        RESONATOR,
        RESONANCE_FREQUENCY,
        RESONATOR_LINEWIDTH,
        FLUX_SWEET_SPOT,
    ),
    primary_key=(RESONATOR,),
    description="Reviewed readout resonator calibration values.",
)
Q0_READOUT = READOUT_RESONATORS.row(RESONATOR.key("q0"))

REFERENCE_PARAMETER_CATALOG = sc.parameter_catalog(
    "reference-lab-parameter-catalog",
    QUBITS,
    READOUT_RESONATORS,
)


def reference_lab_parameter_snapshot() -> ParameterSnapshot:
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
            TableParameterValue(
                id=READOUT_RESONATORS.id,
                rows=(
                    Q0_READOUT.values(
                        RESONANCE_FREQUENCY.value(5.0e9),
                        RESONATOR_LINEWIDTH.value(2.0e6),
                        FLUX_SWEET_SPOT.value(0.0),
                    ),
                ),
            ),
        ),
    )


__all__ = [
    "DRAG_BETA",
    "FLUX_SWEET_SPOT",
    "Q0",
    "Q0_DRAG_BETA",
    "Q0_READOUT",
    "QUARTER_TURN_AMPLITUDE",
    "QUARTER_TURN_DURATION",
    "QUARTER_TURN_SIGMA",
    "QUBIT",
    "QUBITS",
    "READOUT_RESONATORS",
    "REFERENCE_PARAMETER_CATALOG",
    "RESONANCE_FREQUENCY",
    "RESONATOR",
    "RESONATOR_LINEWIDTH",
    "reference_lab_parameter_snapshot",
]
