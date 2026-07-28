from __future__ import annotations

from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.parameter import (
    TableParameterValue,
)

from quantum_lab_demo.configuration import quantum_lab_bootstrap_config


def test_bootstrap_config_provides_valid_drag_compiler_parameters() -> None:
    config = quantum_lab_bootstrap_config()

    assert (
        validate_parameter_snapshot(
            config.parameter_catalog,
            config.parameter_snapshot,
        )
        == ()
    )
    qubits = config.parameter_snapshot.get("qubits")
    assert isinstance(qubits, TableParameterValue)
    q0 = next(
        row
        for row in qubits.rows
        if row["qubit"] == EntityRef(id="q0", kind="logical_qubit")
    )
    assert q0["drag_beta"] == Quantity(value=0.5, unit="ns")
    assert q0["quarter_turn_duration"] == Quantity(value=16, unit="ns")
    assert q0["quarter_turn_amplitude"] == Quantity(value=0.2, unit="arb")
