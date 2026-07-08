"""Reusable parameter references for experiment-system modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.ids import (
    QUBIT_PARAMETER_TABLE,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)


def qubit_param(column: str, *, input_id: str = "qubit"):
    return sc.table_param(
        QUBIT_PARAMETER_TABLE,
        key={"qubit": sc.input(input_id)},
        column=column,
    )


def two_qubit_gate_param(column: str):
    return two_qubit_gate_param_for(
        column,
        control_input_id="control_qubit",
        partner_input_id="partner_qubit",
    )


def two_qubit_gate_param_for(
    column: str,
    *,
    control_input_id: str,
    partner_input_id: str,
):
    return sc.table_param(
        TWO_QUBIT_GATE_PARAMETER_TABLE,
        key={
            "control_qubit": sc.input(control_input_id),
            "partner_qubit": sc.input(partner_input_id),
            "gate": "cz",
        },
        column=column,
    )


__all__ = [
    "qubit_param",
    "two_qubit_gate_param",
    "two_qubit_gate_param_for",
]
