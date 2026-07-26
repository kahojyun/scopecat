"""Accepted parameter schema shared by the demo lab's quantum workflows."""

from __future__ import annotations

import scopecat as sc
from scopecat.kernel.entity import EntityRef

QUBIT_PARAMETER_TABLE = "qubits"
TWO_QUBIT_GATE_PARAMETER_TABLE = "two_qubit_gates"
DRAG_BETA_PARAMETER_COLUMN = "drag_beta"
CZ_AMPLITUDE_PARAMETER_COLUMN = "coupler_amplitude"

_QUBIT_VALUE_TYPE = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_NS_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
_ARB_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))
_QUBIT_PARAMETER_TABLE_TYPE = sc.TableType(
    columns=(
        sc.TableColumn("qubit", _QUBIT_VALUE_TYPE),
        sc.TableColumn("rabi_pulse_length", _NS_VALUE_TYPE),
        sc.TableColumn("rabi_drive_amplitude", _ARB_VALUE_TYPE),
        sc.TableColumn("drag_beta", _NS_VALUE_TYPE),
        sc.TableColumn("drive_frequency", sc.ScalarType(sc.QuantityType(unit="GHz"))),
        sc.TableColumn(
            "readout_frequency",
            sc.ScalarType(sc.QuantityType(unit="GHz")),
        ),
        sc.TableColumn("readout_power", sc.ScalarType(sc.QuantityType(unit="dBm"))),
        sc.TableColumn("x_duration", _NS_VALUE_TYPE),
        sc.TableColumn("x_amplitude", _ARB_VALUE_TYPE),
        sc.TableColumn("quarter_turn_duration", _NS_VALUE_TYPE),
        sc.TableColumn("quarter_turn_amplitude", _ARB_VALUE_TYPE),
        sc.TableColumn("quarter_turn_sigma", _NS_VALUE_TYPE),
        sc.TableColumn("readout_duration", _NS_VALUE_TYPE),
        sc.TableColumn("readout_amplitude", _ARB_VALUE_TYPE),
    ),
    primary_key=("qubit",),
)
_QUBIT_PARAMETERS = sc.parameter(
    QUBIT_PARAMETER_TABLE,
    _QUBIT_PARAMETER_TABLE_TYPE,
)

_Q0 = EntityRef(id="q0", kind="logical_qubit")
_Q1 = EntityRef(id="q1", kind="logical_qubit")
_DRAG_BETA_VALUE_TYPE = _NS_VALUE_TYPE
_CZ_AMPLITUDE_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))


def qubit_parameters() -> sc.ValueRef:
    """Expose the accepted qubit table as one compiler-only collection."""

    return _QUBIT_PARAMETERS


def q0_parameter_key() -> dict[str, EntityRef]:
    """Return the canonical q0 row key for parameter updates and lookups."""

    return {"qubit": _Q0}


_Q0_DRAG_BETA_LOOKUP = sc.parameter_lookup(
    QUBIT_PARAMETER_TABLE,
    key=q0_parameter_key(),
    column=DRAG_BETA_PARAMETER_COLUMN,
    value_type=_DRAG_BETA_VALUE_TYPE,
)


def q0_drag_beta_lookup() -> sc.ValueRef:
    """Reference the accepted q0 DRAG beta cell."""

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


def q0_q1_cz_amplitude_lookup() -> sc.ValueRef:
    """Reference the accepted q0-q1 CZ amplitude cell."""

    return _Q0_Q1_CZ_AMPLITUDE_LOOKUP


__all__ = [
    "CZ_AMPLITUDE_PARAMETER_COLUMN",
    "DRAG_BETA_PARAMETER_COLUMN",
    "QUBIT_PARAMETER_TABLE",
    "TWO_QUBIT_GATE_PARAMETER_TABLE",
    "q0_drag_beta_lookup",
    "q0_parameter_key",
    "q0_q1_cz_amplitude_lookup",
    "q0_q1_cz_parameter_key",
    "qubit_parameters",
]
