"""Accepted parameter schema shared by the demo lab's quantum workflows."""

from __future__ import annotations

import scopecat as sc
from scopecat.kernel.entity import EntityRef

QUBIT_PARAMETER_TABLE = "qubits"
DRAG_BETA_PARAMETER_COLUMN = "drag_beta"

_QUBIT_VALUE_TYPE = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_NS_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
_ARB_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))
QUBIT_PARAMETER_TABLE_TYPE = sc.TableType(
    columns=(
        sc.TableColumn("qubit", _QUBIT_VALUE_TYPE),
        sc.TableColumn("drag_beta", _NS_VALUE_TYPE),
        sc.TableColumn("quarter_turn_duration", _NS_VALUE_TYPE),
        sc.TableColumn("quarter_turn_amplitude", _ARB_VALUE_TYPE),
        sc.TableColumn("quarter_turn_sigma", _NS_VALUE_TYPE),
    ),
    primary_key=("qubit",),
)
_QUBIT_PARAMETERS = sc.parameter(
    QUBIT_PARAMETER_TABLE,
    QUBIT_PARAMETER_TABLE_TYPE,
)

_Q0 = EntityRef(id="q0", kind="logical_qubit")
_DRAG_BETA_VALUE_TYPE = _NS_VALUE_TYPE


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


__all__ = [
    "DRAG_BETA_PARAMETER_COLUMN",
    "QUBIT_PARAMETER_TABLE",
    "QUBIT_PARAMETER_TABLE_TYPE",
    "q0_drag_beta_lookup",
    "q0_parameter_key",
    "qubit_parameters",
]
