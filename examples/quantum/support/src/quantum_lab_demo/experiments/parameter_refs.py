"""Reusable parameter references for experiment-system modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.ids import (
    QUBIT_PARAMETER_TABLE,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)

_QUANTITY = sc.ScalarType(sc.QuantityType())


def qubit_param(column: str, qubit: sc.ValueRef) -> sc.ValueRef:
    return sc.parameter_lookup(
        QUBIT_PARAMETER_TABLE,
        key={"qubit": qubit},
        column=column,
        value_type=_QUANTITY,
    )


def two_qubit_gate_param(
    column: str,
    *,
    control_qubit: sc.ValueRef,
    partner_qubit: sc.ValueRef,
    value_type: sc.ScalarType = _QUANTITY,
) -> sc.ValueRef:
    return two_qubit_gate_param_for(
        column,
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        value_type=value_type,
    )


def two_qubit_gate_param_for(
    column: str,
    *,
    control_qubit: sc.ValueRef,
    partner_qubit: sc.ValueRef,
    value_type: sc.ScalarType = _QUANTITY,
) -> sc.ValueRef:
    return sc.parameter_lookup(
        TWO_QUBIT_GATE_PARAMETER_TABLE,
        key={
            "control_qubit": control_qubit,
            "partner_qubit": partner_qubit,
            "gate": "cz",
        },
        column=column,
        value_type=value_type,
    )


__all__ = [
    "qubit_param",
    "two_qubit_gate_param",
    "two_qubit_gate_param_for",
]
