"""Python-owned initial parameter values for the runnable quantum lab."""

from __future__ import annotations

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.parameter import (
    ParameterAtomValue,
    ParameterSnapshot,
    TableParameterValue,
)


def quantum_lab_parameter_snapshot() -> ParameterSnapshot:
    """Build the initial scalar and calibration tables reviewed in source."""

    return ParameterSnapshot(
        id="templates-parameter-snapshot",
        values=(
            TableParameterValue(
                id="qubits",
                rows=(_q0_drag_row(),),
            ),
        ),
    )


def _q0_drag_row() -> dict[str, ParameterAtomValue]:
    return {
        "qubit": EntityRef(id="q0", kind="logical_qubit"),
        "drag_beta": _quantity(0.5, "ns"),
        "quarter_turn_duration": _quantity(16.0, "ns"),
        "quarter_turn_amplitude": _quantity(0.2, "arb"),
        "quarter_turn_sigma": _quantity(4.0, "ns"),
    }


def _quantity(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit)


__all__ = ["quantum_lab_parameter_snapshot"]
