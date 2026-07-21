"""Accepted parameter schema shared by the demo lab's quantum workflows.

The row and lookup helpers deliberately describe the same immutable cell. This
keeps calibration scans, production programs, and analysis proposals aligned
without giving the domain compiler access to mutable parameter state.
"""

from __future__ import annotations

import scopecat as sc
from scopecat.records.entity import EntityRef

QUBIT_PARAMETER_TABLE = "qubits"
TWO_QUBIT_GATE_PARAMETER_TABLE = "two_qubit_gates"
DRAG_BETA_PARAMETER_COLUMN = "drag_beta"
CZ_AMPLITUDE_PARAMETER_COLUMN = "coupler_amplitude"

_Q0 = EntityRef(id="q0", kind="logical_qubit")
_Q1 = EntityRef(id="q1", kind="logical_qubit")
_DRAG_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
_CZ_AMPLITUDE_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))


def q0_parameter_key() -> dict[str, EntityRef]:
    """Return the canonical q0 row key for parameter updates and lookups."""

    return {"qubit": _Q0}


_Q0_DRAG_BETA_LOOKUP = sc.parameter_lookup(
    QUBIT_PARAMETER_TABLE,
    key=q0_parameter_key(),
    column=DRAG_BETA_PARAMETER_COLUMN,
    value_type=_DRAG_BETA_VALUE_TYPE,
)


def q0_drag_beta_row() -> sc.ParameterRow:
    """Select the q0 row whose accepted DRAG beta centers calibration scans."""

    return sc.param_row(QUBIT_PARAMETER_TABLE, **q0_parameter_key())


def q0_drag_beta_lookup() -> sc.ValueRef:
    """Reference accepted q0 DRAG beta without reading live parameter state."""

    return _Q0_DRAG_BETA_LOOKUP


def q0_q1_cz_parameter_key() -> dict[str, EntityRef | str]:
    """Return the canonical directed q0-q1 CZ row key."""

    return {
        "control_qubit": _Q0,
        "partner_qubit": _Q1,
        "gate": "cz",
    }


_Q0_Q1_CZ_AMPLITUDE_LOOKUP = sc.parameter_lookup(
    TWO_QUBIT_GATE_PARAMETER_TABLE,
    key=q0_q1_cz_parameter_key(),
    column=CZ_AMPLITUDE_PARAMETER_COLUMN,
    value_type=_CZ_AMPLITUDE_VALUE_TYPE,
)


def q0_q1_cz_row() -> sc.ParameterRow:
    """Select the q0-q1 CZ row whose accepted amplitude centers scans."""

    return sc.param_row(
        TWO_QUBIT_GATE_PARAMETER_TABLE,
        **q0_q1_cz_parameter_key(),
    )


def q0_q1_cz_amplitude_lookup() -> sc.ValueRef:
    """Reference accepted q0-q1 CZ amplitude without reading live state."""

    return _Q0_Q1_CZ_AMPLITUDE_LOOKUP


__all__ = [
    "CZ_AMPLITUDE_PARAMETER_COLUMN",
    "DRAG_BETA_PARAMETER_COLUMN",
    "QUBIT_PARAMETER_TABLE",
    "TWO_QUBIT_GATE_PARAMETER_TABLE",
    "q0_drag_beta_lookup",
    "q0_drag_beta_row",
    "q0_parameter_key",
    "q0_q1_cz_amplitude_lookup",
    "q0_q1_cz_parameter_key",
    "q0_q1_cz_row",
]
